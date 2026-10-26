"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";

import type { AuditPage } from "./actions";
import { auditQuery, type AuditFilters } from "./filters";

/** One page of `GET /workspaces/{id}/audit`. */
export async function fetchAuditPage(
  baseUrl: string,
  workspaceId: string,
  filters: AuditFilters,
  cursor: string | null,
  limit: number,
): Promise<AuditPage> {
  let result;
  try {
    result = await createApiClient(baseUrl).GET("/workspaces/{workspace_id}/audit", {
      params: {
        path: { workspace_id: workspaceId },
        query: { ...auditQuery(filters), ...(cursor ? { cursor } : {}), limit },
      },
    });
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
  if (!result.data) {
    throw new Error(`Could not load the audit log (HTTP ${result.response.status}).`);
  }
  return result.data;
}

/** The workspace's audit log narrowed to `filters`, newest first, one page at a time. */
export function useAuditLog(
  filters: AuditFilters,
  {
    workspaceId,
    baseUrl = apiBaseUrl(),
    limit = 50,
  }: { workspaceId: string; baseUrl?: string; limit?: number },
) {
  return useInfiniteQuery({
    queryKey: ["audit", workspaceId, filters, limit],
    queryFn: ({ pageParam }) => fetchAuditPage(baseUrl, workspaceId, filters, pageParam, limit),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}
