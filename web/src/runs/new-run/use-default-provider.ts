import { useQuery } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "@/api/client";

import type { RunProvider } from "./providers";

/** The workspace's default provider (8.3), the sheet's starting choice when the workflow names
 * none. `settled` is false until the answer is in (or failed), so the sheet picks its starting
 * choice once. A workspace whose settings cannot be read starts on Claude. */
export function useDefaultProvider({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}): { provider: RunProvider | null; settled: boolean } {
  const settings = useQuery({
    queryKey: ["provider-settings", workspaceId],
    queryFn: async () => {
      const { data } = await createApiClient(baseUrl).GET(
        "/workspaces/{workspace_id}/provider-settings",
        { params: { path: { workspace_id: workspaceId } } },
      );
      return data?.default_provider ?? null;
    },
    retry: false,
  });
  return { provider: settings.data ?? null, settled: !settings.isPending };
}
