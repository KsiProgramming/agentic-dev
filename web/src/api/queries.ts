"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "./client";
import { ApiError } from "./errors";
import type { components } from "./schema";

export type Template = components["schemas"]["TemplateOut"];
export type Connection = components["schemas"]["ConnectionOut"];
export type Repo = components["schemas"]["RepoOut"];
export type NewRepoOptions = components["schemas"]["NewRepoOptions"];
export type Requirement = Template["requires"][number];
export type WorkspacePricing = components["schemas"]["WorkspacePricing"];
export type ModelPricing = WorkspacePricing["models"][number];
export type Price = components["schemas"]["Price"];
export type PriceOverride = components["schemas"]["PriceOverride"];
export type WorkspacePolicy = components["schemas"]["WorkspacePolicyOut"];
export type RunLimits = components["schemas"]["RunLimits"];
export type RunLimitOverrides = components["schemas"]["RunLimitOverrides"];

/** What the API says about the workspace's GitHub repos. */
export type GithubRepos =
  | { state: "connected"; repos: Repo[] }
  | { state: "not-connected" }
  /** The App was uninstalled or lost access: install it again. */
  | { state: "gone" }
  /** The server has no GitHub App. */
  | { state: "not-configured"; detail: string };

/** Every query about one workspace's connections lives under this key. */
export function connectionsKey(workspaceId: string) {
  return ["workspace", workspaceId, "connections"] as const;
}

export function pricingKey(workspaceId: string) {
  return ["workspace", workspaceId, "pricing"] as const;
}

export function policyKey(workspaceId: string) {
  return ["workspace", workspaceId, "policy"] as const;
}

export function reposKey(workspaceId: string) {
  return ["workspace", workspaceId, "repos"] as const;
}

export function newRepoOptionsKey(workspaceId: string) {
  return ["workspace", workspaceId, "repos", "new-repo-options"] as const;
}

/** Fetch errors become "Could not reach the API." instead of the browser's TypeError. */
async function call<T>(request: () => Promise<T>): Promise<T> {
  try {
    return await request();
  } catch (err) {
    throw err instanceof TypeError ? new Error("Could not reach the API.") : err;
  }
}

export function useTemplates({ baseUrl = apiBaseUrl() }: { baseUrl?: string } = {}) {
  return useQuery({
    queryKey: ["templates"],
    queryFn: async () => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).GET("/templates"),
      );
      if (!data) throw new ApiError(response.status, error, "Could not load the templates");
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useConnections({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  return useQuery({
    queryKey: connectionsKey(workspaceId),
    queryFn: async () => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).GET("/workspaces/{workspace_id}/connections", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not load the connections");
      return data;
    },
  });
}

/** The workspace's GitHub repos. Only asked once GitHub is linked (`enabled`): asking first would
 * log an error response in the browser console. */
export function useRepos({
  workspaceId,
  baseUrl = apiBaseUrl(),
  enabled = true,
}: {
  workspaceId: string;
  baseUrl?: string;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: reposKey(workspaceId),
    enabled,
    queryFn: async (): Promise<GithubRepos> => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).GET("/workspaces/{workspace_id}/repos", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      if (data) return { state: "connected", repos: data };
      const refused = new ApiError(response.status, error, "Could not load the repos");
      if (response.status === 503) return { state: "not-configured", detail: refused.message };
      if (refused.code === "no_connection") return { state: "not-connected" };
      if (refused.code === "installation_gone") return { state: "gone" };
      throw refused;
    },
  });
}

/** Whether runs of the workspace can create their repo, and where. Only asked once a user wants
 * a new repo (`enabled`). */
export function useNewRepoOptions({
  workspaceId,
  baseUrl = apiBaseUrl(),
  enabled = true,
}: {
  workspaceId: string;
  baseUrl?: string;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: newRepoOptionsKey(workspaceId),
    enabled,
    queryFn: async () => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).GET("/workspaces/{workspace_id}/repos/new-repo-options", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      if (!data) {
        throw new ApiError(response.status, error, "Could not check where a repo can be created");
      }
      return data;
    },
  });
}

export function useSaveClaudeKey({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (apiKey: string) => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).PUT("/workspaces/{workspace_id}/connections/claude", {
          params: { path: { workspace_id: workspaceId } },
          body: { api_key: apiKey },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "The API refused the key");
      return data;
    },
    onSuccess: () => queries.invalidateQueries({ queryKey: connectionsKey(workspaceId) }),
  });
}

export function useRemoveClaudeKey({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await call(() =>
        createApiClient(baseUrl).DELETE("/workspaces/{workspace_id}/connections/claude", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      // Already gone is what was asked for.
      if (!response.ok && response.status !== 404) {
        throw new ApiError(response.status, error, "Could not remove the key");
      }
    },
    onSuccess: () => queries.invalidateQueries({ queryKey: connectionsKey(workspaceId) }),
  });
}

/** Starts the GitHub App install and sends the browser to GitHub. `returnTo` is the web app path
 * GitHub's redirect comes back to (the settings page by default). */
export function useStartGithubInstall({
  workspaceId,
  baseUrl = apiBaseUrl(),
  navigate = (url: string) => window.location.assign(url),
}: {
  workspaceId: string;
  baseUrl?: string;
  navigate?: (url: string) => void;
}) {
  return useMutation({
    mutationFn: async (returnTo?: string) => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).POST("/workspaces/{workspace_id}/connections/github/install", {
          params: { path: { workspace_id: workspaceId } },
          body: returnTo ? { return_to: returnTo } : undefined,
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not start the install");
      navigate(data.install_url);
    },
  });
}

export function useDisconnectGithub({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { error, response } = await call(() =>
        createApiClient(baseUrl).DELETE("/workspaces/{workspace_id}/connections/github", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      if (!response.ok && response.status !== 404) {
        throw new ApiError(response.status, error, "Could not disconnect");
      }
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: connectionsKey(workspaceId) });
      void queries.invalidateQueries({ queryKey: reposKey(workspaceId) });
    },
  });
}

/** The model prices the workspace's runs are priced with. */
export function usePricing({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  return useQuery({
    queryKey: pricingKey(workspaceId),
    queryFn: async () => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).GET("/workspaces/{workspace_id}/pricing", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not load the prices");
      return data;
    },
  });
}

/** Replaces the workspace's price overrides; `[]` resets every model to its list price. */
export function useSavePricing({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (overrides: PriceOverride[]) => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).PUT("/workspaces/{workspace_id}/pricing", {
          params: { path: { workspace_id: workspaceId } },
          body: { overrides },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not save the prices");
      return data;
    },
    onSuccess: (pricing) => queries.setQueryData(pricingKey(workspaceId), pricing),
  });
}

/** The run limits the workspace's new runs get. */
export function usePolicy({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  return useQuery({
    queryKey: policyKey(workspaceId),
    queryFn: async () => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).GET("/workspaces/{workspace_id}/policy", {
          params: { path: { workspace_id: workspaceId } },
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not load the run limits");
      return data;
    },
  });
}

/** Replaces the workspace's own run limits; `{}` resets them to the platform's. */
export function useSavePolicy({
  workspaceId,
  baseUrl = apiBaseUrl(),
}: {
  workspaceId: string;
  baseUrl?: string;
}) {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: async (overrides: RunLimitOverrides) => {
      const { data, error, response } = await call(() =>
        createApiClient(baseUrl).PUT("/workspaces/{workspace_id}/policy", {
          params: { path: { workspace_id: workspaceId } },
          body: overrides,
        }),
      );
      if (!data) throw new ApiError(response.status, error, "Could not save the run limits");
      return data;
    },
    onSuccess: (policy) => queries.setQueryData(policyKey(workspaceId), policy),
  });
}
