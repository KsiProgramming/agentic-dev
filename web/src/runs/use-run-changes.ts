"use client";

import { useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import type { components } from "@/api/schema";

import { parseChanges } from "./gates";
import type { GateFile } from "./console/gate-files";

/** The latest saved version of one of a run's branches, with the files it changed (12.3). */
export type SavedBranchChanges = components["schemas"]["SavedBranchChanges"];

export function runChangesKey(runId: string) {
  return ["run", runId, "changes"] as const;
}

/** `GET /runs/{id}/changes`: what the run's writers changed, read from what was saved, so it is
 * there after the sandbox is gone. Fetched only while `enabled` (a sheet that shows it is open). */
export function useRunChanges(
  runId: string,
  { enabled = true, baseUrl = apiBaseUrl() }: { enabled?: boolean; baseUrl?: string } = {},
) {
  return useQuery({
    queryKey: runChangesKey(runId),
    enabled,
    queryFn: async () => {
      let result;
      try {
        result = await createApiClient(baseUrl).GET("/runs/{run_id}/changes", {
          params: { path: { run_id: runId } },
        });
      } catch (err) {
        throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
      }
      if (!result.data) {
        throw new Error(
          `Could not load what the writers changed (HTTP ${result.response.status}).`,
        );
      }
      return result.data;
    },
  });
}

/** What one writer key changed, as the console shows it: its saved branch, or, when the run
 * ended with work it had not committed, that work (which holds the branch's commits too). */
export interface ChangeSet {
  key: string;
  branch: string;
  kind: SavedBranchChanges["kind"];
  /** The version shows uncommitted work, as it was on disk when the run ended. */
  uncommitted: boolean;
  commits: number;
  savedAt: string;
  /** `null` for a version saved before its changes were recorded, or when they could not be
   * read (`error`). */
  files: GateFile[] | null;
  error: string | null;
  /** When its saved commits were dropped; its files are still shown. */
  bundleRemovedAt: string | null;
}

/** One change set per writer key, integration branches first, then writers by key: a writer's
 * uncommitted work stands for its branch. */
export function changeSets(branches: SavedBranchChanges[]): ChangeSet[] {
  const byKey = new Map<string, SavedBranchChanges>();
  for (const branch of branches) {
    const id = `${branch.kind === "integration" ? "0" : "1"}:${branch.key}`;
    const before = byKey.get(id);
    if (!before || branch.kind === "wip") byKey.set(id, branch);
  }
  return [...byKey.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, branch]) => ({
      key: branch.key,
      branch: branch.branch,
      kind: branch.kind,
      uncommitted: branch.kind === "wip",
      commits: branch.commits,
      savedAt: branch.saved_at,
      files:
        branch.changes === null
          ? null
          : parseChanges(branch.changes).map((change) => ({
              change,
              original: change.before ?? "",
              modified: change.after ?? "",
              edited: false,
            })),
      error: branch.changes_error,
      bundleRemovedAt: branch.bundle_removed_at,
    }));
}
