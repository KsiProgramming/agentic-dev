"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";

import type { RunFilters } from "./filters";
import type { RunSummaryPage } from "./summaries";

/** Every runs list of a workspace lives under this query key. */
export function runsKey(workspaceId: string) {
  return ["runs", workspaceId] as const;
}

/** One runs list: its filters and page size. */
export function runListKey(workspaceId: string, filters: RunFilters, limit: number) {
  return ["runs", workspaceId, "list", filters, limit] as const;
}

export type RunListKey = ReturnType<typeof runListKey>;

/** One page of `GET /runs`. */
export async function fetchRunPage(
  baseUrl: string,
  workspaceId: string,
  filters: RunFilters,
  cursor: string | null,
  limit: number,
): Promise<RunSummaryPage> {
  let result;
  try {
    result = await createApiClient(baseUrl).GET("/runs", {
      params: {
        query: {
          workspace_id: workspaceId,
          ...(filters.status.length > 0 ? { status: filters.status } : {}),
          ...(filters.template ? { template: filters.template } : {}),
          ...(filters.repo ? { repo: filters.repo } : {}),
          ...(cursor ? { cursor } : {}),
          limit,
        },
      },
    });
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
  if (!result.data) throw new Error(`Could not load runs (HTTP ${result.response.status}).`);
  return result.data;
}

/** The workspace's runs narrowed to `filters`, newest first, one page at a time. */
export function useRunList(
  filters: RunFilters,
  {
    workspaceId,
    baseUrl = apiBaseUrl(),
    limit = 25,
    enabled = true,
  }: { workspaceId: string; baseUrl?: string; limit?: number; enabled?: boolean },
) {
  return useInfiniteQuery({
    queryKey: runListKey(workspaceId, filters, limit),
    queryFn: ({ pageParam }) => fetchRunPage(baseUrl, workspaceId, filters, pageParam, limit),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}
