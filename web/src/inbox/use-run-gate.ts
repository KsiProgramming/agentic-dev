"use client";

import { useQuery } from "@tanstack/react-query";

import { createApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { components } from "@/api/schema";
import { parseArtifacts } from "@/runs/artifacts/artifacts";
import { parseChanges, type PendingGate } from "@/runs/gates";

type RunGate = components["schemas"]["RunGate"];

/** A writer's branch, which approving lets go on. */
export interface GateBranch {
  nodeId: string;
  branch: string;
}

/** The gate a run waits at, as the Inbox reviews it: what the dock shows, and what approving
 * does (the writers' branches, towards `base` of `repoUrl`). */
export interface InboxGate extends PendingGate {
  repoUrl: string | null;
  /** The branch the writers started from; null for the repo's default branch. */
  base: string | null;
  branches: GateBranch[];
}

export function toInboxGate(body: RunGate): InboxGate {
  return {
    nodeId: body.node_id,
    title: body.title ?? "Approve?",
    prompt: body.prompt ?? null,
    artifact: body.artifact,
    changes: parseChanges(body.changes),
    changesError: body.changes_error ?? null,
    expiresAt: body.expires_at ?? null,
    runArtifacts: parseArtifacts(body.run_artifacts),
    repoUrl: body.repo?.url ?? null,
    base: body.base ?? null,
    branches: body.branches.map((b) => ({ nodeId: b.node_id, branch: b.branch })),
  };
}

/** `GET /runs/{id}/gate` for the gate `nodeId` (from the run's summary), so a later gate of
 * the same run is read again. A run no longer waiting answers 409 (`ApiError`). */
export function useRunGate(
  runId: string,
  nodeId: string | undefined,
  { baseUrl }: { baseUrl: string },
) {
  return useQuery({
    queryKey: ["run-gate", runId, nodeId],
    queryFn: async () => {
      let result;
      try {
        result = await createApiClient(baseUrl).GET("/runs/{run_id}/gate", {
          params: { path: { run_id: runId } },
        });
      } catch (err) {
        throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
      }
      if (!result.data) {
        throw new ApiError(result.response.status, result.error, "Could not load the gate");
      }
      return toInboxGate(result.data);
    },
    // A gate does not change while it waits. An answer from the API (a 409 once the gate is
    // decided) is not tried again; the review's Retry is there for the rest.
    staleTime: Infinity,
    retry: (count, error) => !(error instanceof ApiError) && count < 3,
  });
}
