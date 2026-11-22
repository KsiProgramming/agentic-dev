import type { Requirement } from "@/api/queries";
import { allSpecNodes, type SpecNode, type WorkflowSpec } from "@/runs/graph/spec-graph";

/** Who a run's agents run on (8.3): Claude, or the Copilot of a personal GitHub connection. */
export type RunProvider = "claude" | "copilot";

/** One agent of the run, and where it runs. `pinned`: the node names its own provider, so the
 * run's choice never moves it. */
export interface RunAgent {
  id: string;
  provider: RunProvider;
  pinned: boolean;
}

export interface ResolvedRun {
  agents: RunAgent[];
  /** The providers the run's agents use; with no agent known, the chosen one. */
  uses: Record<RunProvider, boolean>;
}

/** The `provider` a node writes for the agent it runs (`null`: none), or `undefined` when it
 * runs no agent: an agent, a reduce with an agent, a router with a classifier, an orchestrator's
 * hub (the engine's `agent_settings`). */
export function ownProvider(node: SpecNode): RunProvider | null | undefined {
  switch (node.type) {
    case "agent":
      return node.provider ?? null;
    case "reduce":
      return node.agent ? (node.agent.provider ?? null) : undefined;
    case "router":
      return node.classifier ? (node.classifier.provider ?? null) : undefined;
    case "orchestrator":
      return node.hub.provider ?? null;
    default:
      return undefined;
  }
}

/** The provider the sheet starts on: the workflow's own, else the workspace's default, else
 * Claude. */
export function defaultChoice(
  spec: Pick<WorkflowSpec, "provider"> | null | undefined,
  workspaceDefault: RunProvider | null | undefined,
): RunProvider {
  return spec?.provider ?? workspaceDefault ?? "claude";
}

/** Where each agent of the run goes for the run's `choice`, by the engine's order: the node's
 * own provider, then the run's choice (which the sheet always sends, and which already stands for
 * the workflow's and the workspace's). A template has no spec here: all its agents follow the
 * choice. Agents inside called workflows count when the spec carries them. */
export function resolveRun(
  spec: WorkflowSpec | null | undefined,
  choice: RunProvider,
): ResolvedRun {
  const agents: RunAgent[] = [];
  for (const node of spec ? allSpecNodes(spec) : []) {
    const own = ownProvider(node);
    if (own === undefined) continue;
    agents.push({ id: node.id, provider: own ?? choice, pinned: own !== null });
  }
  const uses = { claude: false, copilot: false };
  if (agents.length === 0) uses[choice] = true;
  for (const a of agents) uses[a.provider] = true;
  return { agents, uses };
}

/** The agents a node's own provider keeps off the run's `choice`. */
export function pinnedAway(resolved: ResolvedRun, choice: RunProvider): RunAgent[] {
  return resolved.agents.filter((a) => a.pinned && a.provider !== choice);
}

/** The connections the sheet asks for (lessons 11): what the template or workflow needs, less
 * Claude when no agent runs on it. A Copilot agent needs a personal GitHub account instead, which
 * the provider choice asks for. */
export function requiredFor(
  requires: readonly Requirement[],
  resolved: ResolvedRun,
): Requirement[] {
  return resolved.uses.claude ? [...requires] : requires.filter((r) => r !== "claude");
}
