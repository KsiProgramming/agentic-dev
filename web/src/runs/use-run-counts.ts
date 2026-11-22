"use client";

import { useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import type { components } from "@/api/schema";

import type { RunsQuery } from "./filters";
import { runsKey } from "./use-run-summaries";

export type RunCounts = components["schemas"]["RunCounts"];

/** The counts of a workspace's runs list, under its runs key so a reconnect refreshes them. */
export function runCountsKey(
  workspaceId: string,
  template: string | null,
  repo: string | null,
  provider: string | null = null,
) {
  return [...runsKey(workspaceId), "counts", template, repo, provider] as const;
}

/** How many runs each saved view holds, with the query's template and repo filters. The runs
 * stream refreshes them on every change; the interval drops a gate that expired meanwhile. */
export function useRunCounts(
  { template, repo, provider }: Pick<RunsQuery, "template" | "repo" | "provider">,
  { workspaceId, baseUrl = apiBaseUrl() }: { workspaceId: string; baseUrl?: string },
) {
  return useQuery({
    queryKey: runCountsKey(workspaceId, template, repo, provider),
    queryFn: async (): Promise<RunCounts> => {
      const { data, response } = await createApiClient(baseUrl).GET("/runs/counts", {
        params: {
          query: {
            workspace_id: workspaceId,
            ...(template ? { template } : {}),
            ...(repo ? { repo } : {}),
            ...(provider ? { provider } : {}),
          },
        },
      });
      if (!data) throw new Error(`Could not count runs (HTTP ${response.status}).`);
      return data;
    },
    refetchInterval: 30_000,
  });
}
