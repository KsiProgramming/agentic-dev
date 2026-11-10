import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { orchestratorLoopRun } from "../fixtures/orchestrator-loop-run";
import { specParents } from "../spec-parents";
import { buildTimeline, type Step } from "../timeline";
import { stepEntries, stepRows } from "./step-entries";
import { StepOutput } from "./step-output";

const parents = specParents(orchestratorLoopRun.spec.root);
const REVIEW = "CHANGES: b has no test for the empty case.";

function fixOf(steps: Step[], iteration: number): Step {
  const step = steps[0]!.iterations![iteration - 1]!.steps.find((s) => s.id === "fix");
  if (!step?.orchestrator) throw new Error(`no orchestrator in iteration ${iteration}`);
  return step;
}

describe.each([
  ["with the spec", parents],
  ["from the tags alone", null],
])("an orchestrator in a loop (6.9, %s)", (_, known) => {
  const timeline = buildTimeline(orchestratorLoopRun.events, known);

  it("keeps each iteration's tasks and plan apart", () => {
    const [first, second] = [fixOf(timeline.steps, 1), fixOf(timeline.steps, 2)];
    expect(first.orchestrator!.tasks.map((t) => [t.id, t.status, t.steps.length])).toEqual([
      ["a", "completed", 1],
      ["b", "completed", 1],
    ]);
    expect(second.orchestrator!.tasks.map((t) => [t.id, t.status, t.steps.length])).toEqual([
      ["c", "completed", 1],
    ]);
    expect(second.orchestrator!.rounds[0]!.reason).toBe("Add the test the review asked for.");
  });

  it("knows which iteration each ran in and what the second planned again from", () => {
    const [first, second] = [fixOf(timeline.steps, 1), fixOf(timeline.steps, 2)];
    expect([first.orchestrator!.iteration, first.orchestrator!.feedback]).toEqual([1, null]);
    expect([second.orchestrator!.iteration, second.orchestrator!.feedback]).toEqual([2, REVIEW]);
  });

  it("nests the tasks under their iteration in the step list", () => {
    const entries = stepEntries(timeline.steps);
    expect(entries.map((e) => [e.kind, e.key, e.depth])).toEqual([
      ["step", "review", 0],
      ["scope", "review#1", 1],
      ["step", "review#1/fix", 2],
      ["scope", "review#1/fix.a", 3],
      ["step", "review#1/fix.a/fixer", 4],
      ["scope", "review#1/fix.b", 3],
      ["step", "review#1/fix.b/fixer", 4],
      ["step", "review#1/reviewer", 2],
      ["scope", "review#2", 1],
      ["step", "review#2/fix", 2],
      ["scope", "review#2/fix.c", 3],
      ["step", "review#2/fix.c/fixer", 4],
      ["step", "review#2/reviewer", 2],
    ]);
  });
});

describe("a later iteration's Output", () => {
  const entries = stepEntries(buildTimeline(orchestratorLoopRun.events, parents).steps);
  const rowOf = (key: string) => stepRows(entries).find((r) => r.key === key)!;
  const show = (key: string) =>
    render(
      <StepOutput
        runId="r1"
        step={rowOf(key).step}
        row={rowOf(key)}
        kind="orchestrator"
        entries={entries}
        onSelect={() => {}}
      />,
    );

  it("says what the last iteration ended with, as text, and what it merged on top", () => {
    show("review#2/fix");
    const plan = screen.getByTestId("orchestrator-plan");
    const iteration = within(plan).getByTestId("orchestrator-iteration");
    expect(iteration.textContent).toContain("Iteration 2");
    expect(within(iteration).getByTestId("orchestrator-feedback").textContent).toBe(REVIEW);
    expect(within(plan).getByTestId("orchestrator-integration").textContent).toContain(
      "Merged c into agent/run/fix, on top of a, b",
    );
  });

  it("shows no iteration line for the first iteration", () => {
    show("review#1/fix");
    const plan = screen.getByTestId("orchestrator-plan");
    expect(within(plan).queryByTestId("orchestrator-iteration")).toBeNull();
    expect(within(plan).getByTestId("orchestrator-integration").textContent).toContain(
      "Merged a, b into agent/run/fix",
    );
  });
});
