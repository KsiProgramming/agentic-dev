"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";

import type { RunSummary } from "./summaries";
import { runsKey } from "./use-run-summaries";

/** Runs the command palette shows for one query. */
export const SEARCH_LIMIT = 5;

/** `GET /runs?q=`: the workspace's runs whose id starts with `q`, whose PR is number `q` (`42` or
 * `#42`), or whose workflow name contains it, newest first. */
export async function searchRuns(
  baseUrl: string,
  workspaceId: string,
  q: string,
): Promise<RunSummary[]> {
  let result;
  try {
    result = await createApiClient(baseUrl).GET("/runs", {
      params: { query: { workspace_id: workspaceId, q, limit: SEARCH_LIMIT } },
    });
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
  if (!result.data) throw new Error(`Could not search runs (HTTP ${result.response.status}).`);
  return result.data.items;
}

/** The runs matching `q`; idle while `q` is blank. Under the runs key, so it is fetched again
 * with the runs lists when the runs stream reconnects. */
export function useRunSearch(
  q: string,
  { workspaceId, baseUrl = apiBaseUrl() }: { workspaceId: string; baseUrl?: string },
) {
  const query = q.trim();
  return useQuery({
    queryKey: [...runsKey(workspaceId), "search", query] as const,
    queryFn: () => searchRuns(baseUrl, workspaceId, query),
    enabled: query !== "",
    placeholderData: keepPreviousData,
  });
}
