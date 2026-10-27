import type { Step, StepStatus } from "../timeline";
import { allSpecNodes, type SpecNode, type WorkflowSpec } from "./spec-graph";

/** A spec node's status: a step's, or `not_started` while the run has not reached it. */
export type NodeStatus = StepStatus | "not_started";

export interface NodeState {
  status: NodeStatus;
  /** For a map, a parallel or a loop: how far it got, e.g. "2 of 3 items · 1 failed",
   * "2 of 3 branches · any", "Iteration 2 of 5". */
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

/** The state of every node of `spec` (sequences left out), from the run's timeline. */
export function nodeStatuses(spec: WorkflowSpec, steps: Step[]): Map<string, NodeState> {
  const byId = stepsById(steps);
  const states = new Map<string, NodeState>();
  for (const node of allSpecNodes(spec)) {
    if (node.type === "sequence") continue;
    const runs = byId.get(node.id) ?? [];
    states.set(node.id, {
      status: aggregate(runs.map((step) => step.status)),
      summary:
        runs.length === 0
          ? null
          : node.type === "map"
            ? mapSummary(runs)
            : node.type === "parallel"
              ? parallelSummary(runs, node)
              : node.type === "loop"
                ? loopSummary(runs, node.max_iterations)
                : null,
    });
  }
  return states;
}

/**
 * What node `nodeId` did, to show it on its own. A node run once is its step. A node inside a
 * map, a parallel or a loop is shown inside its outermost container, which keeps only the items,
 * branches and iterations that ran it, each holding only that node's run: one entry per item,
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
    if (items.length > 0 || branches.length > 0 || iterations.length > 0) {
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
      };
    }
  }
  return steps.find((step) => step.id === nodeId) ?? null;
}
