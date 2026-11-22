"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { components } from "@/api/schema";

export type ProviderSettings = components["schemas"]["ProviderSettings"];
export type ProviderSettingsBody = components["schemas"]["PutProviderSettings"];

export const providerSettingsKey = (workspaceId: string) =>
  ["workspaces", workspaceId, "provider-settings"] as const;

/** The workspace's provider settings (8.3): default provider, Copilot model, AI credit price. */
export function useProviderSettings({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  return useQuery({
    queryKey: providerSettingsKey(workspaceId),
    queryFn: async () => {
      const { data, error, response } = await createApiClient(baseUrl).GET(
        "/workspaces/{workspace_id}/provider-settings",
        { params: { path: { workspace_id: workspaceId } } },
      );
      if (!data) {
        throw new ApiError(response.status, error, "Could not load the provider settings");
      }
      return data;
    },
  });
}

/** Replaces the workspace's provider settings; they apply to runs created afterwards. */
export function useSaveProviderSettings({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProviderSettingsBody) => {
      const { data, error, response } = await createApiClient(baseUrl).PUT(
        "/workspaces/{workspace_id}/provider-settings",
        { params: { path: { workspace_id: workspaceId } }, body },
      );
      if (!data) {
        throw new ApiError(response.status, error, "Could not save the provider settings");
      }
      return data;
    },
    onSuccess: (settings) => queries.setQueryData(providerSettingsKey(workspaceId), settings),
  });
}
