"use client";

import { useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import type { components } from "@/api/schema";

/** One run as `GET /runs/{id}` describes it: the summary plus its input and failure reason. */
export type RunDetail = components["schemas"]["RunDetail"];

export function runDetailKey(runId: string) {
  return ["run", runId] as const;
}

/** `GET /runs/{id}`; `null` when there is no such run. */
export async function fetchRunDetail(baseUrl: string, runId: string): Promise<RunDetail | null> {
  let result;
  try {
    result = await createApiClient(baseUrl).GET("/runs/{run_id}", {
      params: { path: { run_id: runId } },
    });
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
  if (result.response.status === 404) return null;
  if (!result.data) throw new Error(`Could not load the run (HTTP ${result.response.status}).`);
  return result.data;
}

/** The run's summary. The console keeps it fresh by refetching when its event stream moves on. */
export function useRunDetail(runId: string, baseUrl = apiBaseUrl()) {
  return useQuery({
    queryKey: runDetailKey(runId),
    queryFn: () => fetchRunDetail(baseUrl, runId),
  });
}
