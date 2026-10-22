import type { Step, Timeline } from "../timeline";
import { itemName } from "./item-name";
import { describeTool } from "./tool-describe";

/** What a running run is doing right now, for the live line at the end of the timeline. */
export interface Activity {
  /** Where: the node, or the map item it runs for. */
  where: string;
  /** What: "Reading src/app.ts", "Writing", "Thinking". */
  doing: string;
  target: string;
  /** How many steps run at once (a map's items run in parallel). */
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
    for (const iteration of step.iterations ?? []) runningSteps(iteration.steps, where, out);
    // A map or loop is running while its children are; only leaf steps do the work.
    if (step.status === "running" && !step.items && !step.iterations) {
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
    doing = d.doing;
    target = d.target;
  } else if (last?.kind === "message" && !last.final) {
    doing = "Writing";
  }
  return { where: latest.where, doing, target, running: running.length };
}
