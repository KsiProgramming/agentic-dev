"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiBaseUrl, createApiClient } from "./client";
import { ApiError } from "./errors";
import type { components } from "./schema";

export type Template = components["schemas"]["TemplateOut"];
export type Connection = components["schemas"]["ConnectionOut"];
export type Repo = components["schemas"]["RepoOut"];
export type Requirement = Template["requires"][number];

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

export function reposKey(workspaceId: string) {
  return ["workspace", workspaceId, "repos"] as const;
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
