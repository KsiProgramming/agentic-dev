import { nodeStatuses } from "../graph/node-status";
import type { WorkflowSpec } from "../graph/spec-graph";
import type { Step } from "../timeline";

export interface StepsProgress {
  done: number;
  total: number;
  failed: number;
  running: number;
}

/** How far the run got through its workflow: the spec's nodes (sequences left out), counted the
 * way the graph colours them, so the tile and the graph agree. */
export function stepsProgress(spec: WorkflowSpec, steps: Step[]): StepsProgress {
  const progress = { done: 0, total: 0, failed: 0, running: 0 };
  for (const state of nodeStatuses(spec, steps).values()) {
    progress.total += 1;
    if (state.status === "completed") progress.done += 1;
    else if (state.status === "failed") progress.failed += 1;
    else if (state.status === "running") progress.running += 1;
  }
  return progress;
}

/** "#42" for a pull request's URL. */
export function pullRequestNumber(url: string): string {
  return `#${url.split("/").at(-1)}`;
}
