"use client";

import { useConnections, useRepos, type Repo, type Requirement } from "@/api/queries";
import { allSpecNodes, type WorkflowSpec } from "@/runs/graph/spec-graph";

/** Whether one connection a template needs is there. `attention`: it was, but the GitHub App was
 * uninstalled or lost access. */
export type ConnectionState = "loading" | "ready" | "missing" | "attention" | "error";

export interface Readiness {
  state: Record<Requirement, ConnectionState>;
  /** The GitHub repos, once GitHub is ready. */
  repos: Repo[];
  /** The installation's settings page on GitHub. */
  manageUrl: string | null;
  /** Why loading failed, if it did. */
  error: string | null;
  retry: () => void;
}

/** What the workspace has of the connections templates need. Repos are only asked for once
 * GitHub is linked. */
export function useReadiness({
  workspaceId,
  baseUrl,
}: {
  workspaceId: string;
  baseUrl?: string;
}): Readiness {
  const connections = useConnections({ workspaceId, baseUrl });
  const github = connections.data?.find((c) => c.provider === "github") ?? null;
  const repos = useRepos({ workspaceId, baseUrl, enabled: github !== null });

  const claude: ConnectionState = connections.isPending
    ? "loading"
    : connections.isError
      ? "error"
      : connections.data.some((c) => c.provider === "claude")
        ? "ready"
        : "missing";

  let githubState: ConnectionState;
  if (connections.isPending) githubState = "loading";
  else if (connections.isError) githubState = "error";
  else if (github === null) githubState = "missing";
  else if (repos.isPending) githubState = "loading";
  else if (repos.isError) githubState = "error";
  else if (repos.data.state === "connected") githubState = "ready";
  else if (repos.data.state === "gone") githubState = "attention";
  else githubState = "missing";

  return {
    state: { claude, github: githubState },
    repos: repos.data?.state === "connected" ? repos.data.repos : [],
    manageUrl: github?.manage_url ?? null,
    error: connections.error?.message ?? repos.error?.message ?? null,
    retry: () => {
      void connections.refetch();
      if (github !== null) void repos.refetch();
    },
  };
}

/** Whether every one of `requires` is ready. */
export function isReady(readiness: Readiness, requires: readonly Requirement[]): boolean {
  return requires.every((r) => readiness.state[r] === "ready");
}

export const REQUIREMENT_LABEL: Record<Requirement, string> = {
  claude: "Claude",
  github: "GitHub",
};

/** Tools that work on the run's repo, so a run of a node naming one needs GitHub (the engine's
 * `REPO_TOOL_PREFIXES`). */
const REPO_TOOL_PREFIXES = ["repo.", "github.", "scan."];

/** The connections a stored workflow needs to run (5.7): Claude for its agents, GitHub when a
 * tool works on the repo. */
export function workflowRequires(spec: WorkflowSpec): Requirement[] {
  const nodes = allSpecNodes(spec);
  const tools = nodes.flatMap((n) =>
    n.type === "agent" ? (n.tools ?? []) : n.type === "tool" ? [n.tool] : [],
  );
  const requires: Requirement[] = [];
  if (nodes.some((n) => n.type === "agent")) requires.push("claude");
  if (tools.some((t) => REPO_TOOL_PREFIXES.some((p) => t.startsWith(p)))) requires.push("github");
  return requires;
}
