import { calledRoot } from "../calls";
import type { Step, StepStatus } from "../timeline";
import {
  allSpecNodes,
  routeNodeId,
  routesOf,
  type SpecNode,
  type WorkflowSpec,
} from "./spec-graph";

/** A spec node's status: a step's, `not_started` while the run has not reached it, or
 * `skipped` when it is on a route its router did not take (4.6). */
export type NodeStatus = StepStatus | "not_started" | "skipped";

export interface NodeState {
  status: NodeStatus;
  /** For a map, a parallel, a loop or a router: how far it got, e.g. "2 of 3 items · 1 failed",
   * "2 of 3 branches · any", "Iteration 2 of 5", "Routed to fix_first". */
  summary: string | null;
}

/** When a node ran several times (once per map item or loop iteration), what needs attention
 * first: a failure, then a waiting gate, then work still going on. */
const PRIORITY: NodeStatus[] = ["failed", "waiting", "running", "cancelled", "completed"];

function aggregate(statuses: NodeStatus[]): NodeStatus {
  return PRIORITY.find((status) => statuses.includes(status)) ?? "not_started";
}

/** Every step of the timeline, nested ones included, by node id. */
function stepsById(steps: Step[]): Map<string, Step[]> {
  const byId = new Map<string, Step[]>();
  const visit = (list: Step[]) => {
    for (const step of list) {
      byId.set(step.id, [...(byId.get(step.id) ?? []), step]);
      for (const item of step.items ?? []) visit(item.steps);
      for (const branch of step.branches ?? []) visit(branch.steps);
      for (const iteration of step.iterations ?? []) visit(iteration.steps);
      if (step.router) visit(step.router.steps);
      if (step.subflow) visit(step.subflow.steps);
      for (const task of step.orchestrator?.tasks ?? []) visit(task.steps);
    }
  };
  visit(steps);
  return byId;
}

function plural(n: number, word: string): string {
  if (n === 1) return `${n} ${word}`;
  return `${n} ${word}${word.endsWith("ch") ? "es" : "s"}`;
}

function mapSummary(runs: Step[]): string | null {
  const items = runs.flatMap((step) => step.items ?? []);
  const counts = runs.map((step) => step.itemCount);
  const total = counts.every((n) => n !== null)
    ? counts.reduce((sum, n) => sum + (n ?? 0), 0)
    : null;
  if (total === null && items.length === 0) return null;
  const done = items.filter((item) => item.status !== "running").length;
  const failed = items.filter((item) => item.status === "failed").length;
  const progress =
    total === null ? `${plural(done, "item")} done` : `${done} of ${plural(total, "item")}`;
  return failed > 0 ? `${progress} · ${failed} failed` : progress;
}

type ParallelSpec = Extract<SpecNode, { type: "parallel" }>;
type RouterSpec = Extract<SpecNode, { type: "router" }>;

/** How a parallel joins, in a word or two: "all", "any", "quorum 2". */
export function joinLabel(node: ParallelSpec): string {
  return node.join === "quorum" ? `quorum ${node.quorum ?? node.branches.length}` : node.join;
}

function parallelSummary(runs: Step[], node: ParallelSpec): string | null {
  const branches = runs.flatMap((step) => step.branches ?? []);
  if (branches.length === 0) return null;
  const done = branches.filter((b) => b.status !== "running").length;
  const parts = [`${done} of ${plural(node.branches.length, "branch")}`, joinLabel(node)];
  const failed = branches.filter((b) => b.status === "failed").length;
  const cancelled = branches.filter((b) => b.status === "cancelled").length;
  if (failed > 0) parts.push(`${failed} failed`);
  if (cancelled > 0) parts.push(`${cancelled} cancelled`);
  return parts.join(" · ");
}

function loopSummary(runs: Step[], maxIterations: number): string | null {
  const iterations = Math.max(0, ...runs.map((step) => step.iterations?.length ?? 0));
  return iterations > 0 ? `Iteration ${iterations} of ${maxIterations}` : null;
}

/** The routes a router's runs took, in the order of its routes. */
function chosenRoutes(runs: Step[], node: RouterSpec): string[] {
  const chosen = new Set(runs.flatMap((step) => (step.router?.chosen ? [step.router.chosen] : [])));
  return routesOf(node)
    .map(([id]) => id)
    .filter((id) => chosen.has(id));
}

function routerSummary(runs: Step[], node: RouterSpec): string | null {
  const chosen = chosenRoutes(runs, node);
  if (chosen.length > 0) return `Routed to ${chosen.join(", ")}`;
  return runs.some((step) => step.status === "running") ? "Choosing a route" : null;
}

/** How far an orchestrator got, short enough for its card: "Planning", "2 of 4 tasks ·
 * round 2", "3 of 6 tasks · 2 rounds". */
function orchestratorSummary(runs: Step[]): string | null {
  const info = runs.at(-1)?.orchestrator;
  if (!info) return null;
  const live = runs.at(-1)!.status === "running";
  if (info.tasks.length === 0) {
    if (live) return "Planning";
    return info.rounds.length > 0 ? "Planned no task" : null;
  }
  const done = info.tasks.filter((t) => t.status === "completed").length;
  const parts = [`${done} of ${plural(info.tasks.length, "task")}`];
  if (info.rounds.length > 1) {
    parts.push(live ? `round ${info.rounds.length}` : `${info.rounds.length} rounds`);
  }
  return parts.join(" · ");
}

/** Every node under `node`, itself included. */
function* under(node: SpecNode): Generator<SpecNode> {
  yield node;
  if (node.type === "sequence") for (const step of node.steps) yield* under(step);
  if (node.type === "loop" || node.type === "map" || node.type === "orchestrator") {
    yield* under(node.body);
  }
  if (node.type === "parallel") for (const branch of node.branches) yield* under(branch);
  if (node.type === "router") for (const [, route] of routesOf(node)) yield* under(route);
  const called = calledRoot(node);
  if (called) yield* under(called);
}

/** How far the workflow a subflow called got (6.5): its steps done of all of them. */
function subflowSummary(runs: Step[], node: SpecNode): string | null {
  const called = calledRoot(node);
  const step = runs.at(-1);
  if (!called || !step?.subflow) return null;
  const total = [...under(called)].filter((n) => n.type !== "sequence").length;
  const done = new Set(
    [...stepsById(step.subflow.steps).values()]
      .flat()
      .filter((s) => s.status === "completed")
      .map((s) => s.id),
  ).size;
  const failed = [...stepsById(step.subflow.steps).values()]
    .flat()
    .some((s) => s.status === "failed");
  return `${done} of ${plural(total, "step")}${failed ? " · 1 failed" : ""}`;
}

/** The routes the routers of `spec` did not take, by `routeNodeId`, and every node on them: a
 * route is skipped once its router chose another one (every run of it, in a map or a loop). */
function skippedIds(spec: WorkflowSpec, byId: Map<string, Step[]>): Set<string> {
  const skipped = new Set<string>();
  for (const node of allSpecNodes(spec)) {
    if (node.type !== "router") continue;
    const chosen = chosenRoutes(byId.get(node.id) ?? [], node);
    if (chosen.length === 0) continue;
    for (const [routeId, route] of routesOf(node)) {
      if (chosen.includes(routeId)) continue;
      skipped.add(routeNodeId(node.id, routeId));
      for (const inner of under(route)) skipped.add(inner.id);
    }
  }
  return skipped;
}

/** The state of every node of `spec` (sequences left out), from the run's timeline. A node on a
 * route its router did not take is `skipped`. */
export function nodeStatuses(spec: WorkflowSpec, steps: Step[]): Map<string, NodeState> {
  const byId = stepsById(steps);
  const skipped = skippedIds(spec, byId);
  const states = new Map<string, NodeState>();
  for (const node of allSpecNodes(spec)) {
    if (node.type === "sequence") continue;
    const runs = byId.get(node.id) ?? [];
    states.set(node.id, {
      status:
        runs.length === 0 && skipped.has(node.id)
          ? "skipped"
          : aggregate(runs.map((step) => step.status)),
      summary:
        runs.length === 0
          ? null
          : node.type === "map"
            ? mapSummary(runs)
            : node.type === "parallel"
              ? parallelSummary(runs, node)
              : node.type === "loop"
                ? loopSummary(runs, node.max_iterations)
                : node.type === "router"
                  ? routerSummary(runs, node)
                  : node.type === "orchestrator"
                    ? orchestratorSummary(runs)
                    : node.type === "subflow"
                      ? subflowSummary(runs, node)
                      : null,
    });
  }
  return states;
}

/** The state of each route of the routers of `spec`, by `routeNodeId`: `skipped` once its router
 * took another route, else `not_started` (the route's own nodes say how far it got). */
export function routeStates(spec: WorkflowSpec, steps: Step[]): Map<string, NodeState> {
  const skipped = skippedIds(spec, stepsById(steps));
  const states = new Map<string, NodeState>();
  for (const node of allSpecNodes(spec)) {
    if (node.type !== "router") continue;
    for (const [routeId] of routesOf(node)) {
      const id = routeNodeId(node.id, routeId);
      states.set(id, { status: skipped.has(id) ? "skipped" : "not_started", summary: null });
    }
  }
  return states;
}

/**
 * What node `nodeId` did, to show it on its own. A node run once is its step. A node inside a
 * map, a parallel, a loop, a router, an orchestrator or a subflow is shown inside its outermost container,
 * which keeps only the items, branches, iterations and tasks that ran it, each holding only that node's run: one entry per item,
 * branch or iteration.
 * `null` if the node has not run.
 *
 * Node ids are unique in a spec, so a node that ran inside a container belongs there, even if
 * an event without an `item` (e.g. a budget stop) also put a step of it at this level.
 */
export function focusStep(steps: Step[], nodeId: string): Step | null {
  for (const step of steps) {
    const items = (step.items ?? []).flatMap((item) => {
      const found = focusStep(item.steps, nodeId);
      return found ? [{ ...item, steps: [found] }] : [];
    });
    const branches = (step.branches ?? []).flatMap((branch) => {
      const found = focusStep(branch.steps, nodeId);
      return found ? [{ ...branch, steps: [found] }] : [];
    });
    const iterations = (step.iterations ?? []).flatMap((iteration) => {
      const found = focusStep(iteration.steps, nodeId);
      return found ? [{ ...iteration, steps: [found] }] : [];
    });
    const routed = step.router ? focusStep(step.router.steps, nodeId) : null;
    const called = step.subflow ? focusStep(step.subflow.steps, nodeId) : null;
    const tasks = (step.orchestrator?.tasks ?? []).flatMap((task) => {
      const found = focusStep(task.steps, nodeId);
      return found ? [{ ...task, steps: [found] }] : [];
    });
    if (
      items.length > 0 ||
      branches.length > 0 ||
      iterations.length > 0 ||
      routed ||
      called ||
      tasks.length > 0
    ) {
      // The container's own turns, usage and outcome are not the node's.
      return {
        ...step,
        turns: [],
        usage: null,
        gate: null,
        prUrl: null,
        createdRepo: null,
        error: null,
        items: step.items ? items : null,
        branches: step.branches ? branches : null,
        iterations: step.iterations ? iterations : null,
        router: step.router ? { ...step.router, steps: routed ? [routed] : [] } : null,
        subflow: step.subflow ? { ...step.subflow, steps: called ? [called] : [] } : null,
        orchestrator: step.orchestrator ? { ...step.orchestrator, tasks } : null,
      };
    }
  }
  return steps.find((step) => step.id === nodeId) ?? null;
}
