"use client";

import { useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import type { components } from "@/api/schema";

/** One of the run's artifacts, its latest version, as `GET /runs/{id}/artifacts` lists it. */
export type RunArtifact = components["schemas"]["RunArtifact"];
export type RunArtifactContent = components["schemas"]["RunArtifactContent"];

async function call<T>(request: () => Promise<{ data?: T; response: Response }>): Promise<T> {
  let result;
  try {
    result = await request();
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
  if (result.data === undefined) {
    throw new Error(`Could not load the artifacts (HTTP ${result.response.status}).`);
  }
  return result.data;
}

/** `GET /runs/{id}/artifacts`. `written` (how many `artifact_written` events the page has)
 * is in the key, so the list is read again whenever the run writes one. */
export function useRunArtifacts(runId: string, written: number, baseUrl = apiBaseUrl()) {
  return useQuery({
    queryKey: ["run-artifacts", runId, written],
    queryFn: () =>
      call(() =>
        createApiClient(baseUrl).GET("/runs/{run_id}/artifacts", {
          params: { path: { run_id: runId } },
        }),
      ),
    placeholderData: (previous) => previous,
  });
}

/** `GET /runs/{id}/artifacts/{name}?version=`, while `enabled`. A version never changes. */
export function useRunArtifact(
  runId: string,
  name: string,
  version: number,
  { enabled = true, baseUrl = apiBaseUrl() }: { enabled?: boolean; baseUrl?: string } = {},
) {
  return useQuery({
    queryKey: ["run-artifact", runId, name, version],
    queryFn: () =>
      call(() =>
        createApiClient(baseUrl).GET("/runs/{run_id}/artifacts/{name}", {
          params: { path: { run_id: runId, name }, query: { version } },
        }),
      ),
    enabled,
    staleTime: Infinity,
  });
}
