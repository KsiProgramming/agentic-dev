"use client";

import { useConnections, useJira, useRepos, type Repo, type Requirement } from "@/api/queries";
import { allSpecNodes, type WorkflowSpec } from "@/runs/graph/spec-graph";

/** Whether one connection a template needs is there. `attention`: it was, but the GitHub App was
 * uninstalled or lost access, or Atlassian refused the Jira grant (7.1). */
export type ConnectionState = "loading" | "ready" | "missing" | "attention" | "error";

export interface Readiness {
  state: Record<Requirement, ConnectionState>;
  /** The GitHub repos, once GitHub is ready. */
  repos: Repo[];
  /** The installation's settings page on GitHub. */
  manageUrl: string | null;
  /** Whether the API has an Atlassian app, so Jira can be connected at all. */
  jiraConfigured: boolean;
  /** Why loading failed, if it did. */
  error: string | null;
  retry: () => void;
}

/** What the workspace has of the connections templates need. Repos are only asked for once
 * GitHub is linked. Jira is ready once it is connected and needs no attention (7.2). */
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
  const jira = useJira({ workspaceId, baseUrl });

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

  const jiraState: ConnectionState = jira.isPending
    ? "loading"
    : jira.isError
      ? "error"
      : jira.data.status === "connected"
        ? "ready"
        : jira.data.status === "needs_attention"
          ? "attention"
          : "missing";

  return {
    state: { claude, github: githubState, jira: jiraState },
    repos: repos.data?.state === "connected" ? repos.data.repos : [],
    manageUrl: github?.manage_url ?? null,
    jiraConfigured: jira.data?.configured ?? true,
    error: connections.error?.message ?? repos.error?.message ?? jira.error?.message ?? null,
    retry: () => {
      void connections.refetch();
      if (github !== null) void repos.refetch();
      void jira.refetch();
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
  jira: "Jira",
};

/** Tools that work on the run's repo, so a run of a node naming one needs GitHub (the engine's
 * `REPO_TOOL_PREFIXES`). */
const REPO_TOOL_PREFIXES = ["repo.", "github.", "scan."];

/** The connections a stored workflow needs to run (5.7): Claude for its agents, GitHub when a
 * tool works on the repo, Jira when a node names a `jira.*` tool (7.2). */
export function workflowRequires(spec: WorkflowSpec): Requirement[] {
  const nodes = allSpecNodes(spec);
  const tools = nodes.flatMap((n) =>
    n.type === "agent"
      ? (n.tools ?? [])
      : n.type === "tool"
        ? [n.tool]
        : n.type === "orchestrator"
          ? (n.hub.tools ?? [])
          : [],
  );
  const requires: Requirement[] = [];
  // An orchestrator's hub is an agent too (6.1); it may read the repo (6.9).
  if (nodes.some((n) => n.type === "agent" || n.type === "orchestrator")) requires.push("claude");
  if (tools.some((t) => REPO_TOOL_PREFIXES.some((p) => t.startsWith(p)))) requires.push("github");
  if (tools.some((t) => t.startsWith("jira."))) requires.push("jira");
  return requires;
}
