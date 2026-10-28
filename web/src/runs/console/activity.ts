import type { Step, Timeline } from "../timeline";
import { itemName } from "./item-name";
import { describeTool } from "./tool-describe";

/** What a running run is doing right now, for the live line at the end of the timeline. */
export interface Activity {
  /** Where: the node, or the map item it runs for. */
  where: string;
  /** What: the call's intent ("Read the frontend config"), else "Reading src/app.ts",
   * "Writing", "Thinking". */
  doing: string;
  target: string;
  /** How many steps run at once (a map's items and a parallel's branches run together). */
  running: number;
}

interface Running {
  step: Step;
  where: string;
}

function runningSteps(steps: Step[], where: (step: Step) => string, out: Running[]) {
  for (const step of steps) {
    if (step.items) {
      for (const item of step.items) {
        const label = itemName(item.item, item.index).name;
        runningSteps(item.steps, () => label, out);
      }
    }
    for (const branch of step.branches ?? []) runningSteps(branch.steps, where, out);
    for (const iteration of step.iterations ?? []) runningSteps(iteration.steps, where, out);
    if (step.router) runningSteps(step.router.steps, where, out);
    // A map, parallel or loop is running while its children are; only leaf steps do the work. A
    // router works itself while it chooses (its classifier), then its route does.
    const container = step.items || step.branches || step.iterations || step.router?.chosen;
    if (step.status === "running" && !container) {
      out.push({ step, where: where(step) });
    }
  }
}

/** The latest running step's current action, or `null` if nothing is running. */
export function currentActivity(timeline: Timeline): Activity | null {
  const running: Running[] = [];
  runningSteps(timeline.steps, (s) => s.id, running);
  const latest = running.at(-1);
  if (!latest) return null;
  const last = latest.step.turns.at(-1);
  let doing = "Thinking";
  let target = "";
  if (last?.kind === "tool" && last.status === "running") {
    const d = describeTool(last.name, last.arguments);
    doing = last.intent ?? d.doing;
    target = last.intent ? "" : d.target;
  } else if (last?.kind === "message" && !last.final) {
    doing = "Writing";
  }
  return { where: latest.where, doing, target, running: running.length };
}
