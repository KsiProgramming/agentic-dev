"use client";

import { useQuery } from "@tanstack/react-query";

import { createApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { components } from "@/api/schema";
import { parseBreaker } from "@/runs/breaker";
import { parseArtifacts } from "@/runs/artifacts/artifacts";
import { parseEvidence } from "@/runs/evidence";
import { parseReview } from "@/runs/review";
import {
  parseChanges,
  parseProtectedAttempts,
  parseSelection,
  pausedTitle,
  type PendingGate,
} from "@/runs/gates";

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
  const breaker = parseBreaker(body.breaker);
  return {
    nodeId: body.node_id,
    title: breaker ? pausedTitle(breaker) : (body.title ?? "Approve?"),
    prompt: body.prompt ?? null,
    artifact: body.artifact,
    changes: parseChanges(body.changes),
    changesError: body.changes_error ?? null,
    expiresAt: body.expires_at ?? null,
    runArtifacts: parseArtifacts(body.run_artifacts),
    select: parseSelection(body.select),
    onReject: body.on_reject === "end" ? "end" : "cancel",
    changesLeft: body.changes_left ?? 0,
    iteration: body.iteration ?? 1,
    waitFor: null, // a wait is not reviewed in the Inbox (7.9)
    evidence: parseEvidence(body.evidence),
    review: parseReview(body.review),
    protectedAttempts: parseProtectedAttempts(body.protected_attempts),
    breaker,
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
  { baseUrl, since }: { baseUrl: string; since?: string | null },
) {
  return useQuery({
    // `since` (when the gate expires) tells one pass of a gate in a loop from the next (7.8).
    queryKey: ["run-gate", runId, nodeId, since ?? null],
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
