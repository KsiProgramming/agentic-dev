import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { calledRoot, withCalls } from "./calls";
import { stepEntries, stepOutline, stepRows } from "./console/step-entries";
import { subflowRun, subflowRunUntil } from "./fixtures/subflow-run";
import { allSpecNodes } from "./graph/spec-graph";
import { focusStep, nodeStatuses } from "./graph/node-status";
import { RunMap } from "./graph/run-map";
import { specParents } from "./spec-parents";
import { buildTimeline, stepUsage, stepsUsage, type Step } from "./timeline";

const spec = withCalls(subflowRun.spec, subflowRun.calls);
const parents = specParents(spec.root);
const started = (id: string) =>
  subflowRun.events.find((e) => e.type === "node_started" && e.node_id === id)!.seq;

function review(steps: Step[]): Step {
  const step = steps.find((s) => s.id === "review");
  if (!step?.subflow) throw new Error("no subflow step");
  return step;
}

describe("the run's calls (6.5)", () => {
  it("attach each called root to its subflow, without changing the API's spec", () => {
    const [, call] = allSpecNodes(spec).filter((n) => n.type === "subflow" || n.id === "main");
    expect(call?.id).toBe("review");
    expect(calledRoot(call!)?.id).toBe("review-main");
    expect(calledRoot(subflowRun.spec.root)).toBeNull();
    expect(allSpecNodes(spec).map((n) => n.id)).toEqual([
      "main",
      "agent_1",
      "review",
      "review-main",
      "review-agent_1",
      "verdict",
      "summary",
    ]);
    expect(parents.get("verdict")).toEqual({ container: "review", kind: "subflow", branch: null });
  });

  it("leave a spec with no calls as it is", () => {
    expect(withCalls(subflowRun.spec, {})).toBe(subflowRun.spec);
  });
});

describe.each([
  ["with the spec", parents],
  ["from the tags alone", null],
])("a subflow in the timeline (%s)", (_, known) => {
  const timeline = buildTimeline(subflowRun.events, known);

  it("holds the called workflow's steps", () => {
    expect(timeline.steps.map((s) => s.id)).toEqual(["agent_1", "review", "summary"]);
    const step = review(timeline.steps);
    expect(step.subflow!.workflow).toEqual({ id: "checks", version: 2, name: "Checks" });
    expect(step.subflow!.steps.map((s) => [s.id, s.status])).toEqual([
      ["review-agent_1", "completed"],
      ["verdict", "completed"],
    ]);
  });

  it("costs what its steps cost", () => {
    const step = review(timeline.steps);
    expect(step.usage).toBeNull();
    expect(stepUsage(step)).toEqual(stepsUsage(step.subflow!.steps));
    expect(stepUsage(step)).not.toBeNull();
  });
});

describe("a subflow in the step list", () => {
  it("nests the called steps under it, keyed `<subflow>/<node>`", () => {
    const rows = stepRows(stepEntries(buildTimeline(subflowRun.events, parents).steps));
    expect(rows.map((r) => [r.key, r.depth])).toEqual([
      ["agent_1", 0],
      ["review", 0],
      ["review/review-agent_1", 1],
      ["review/verdict", 1],
      ["summary", 0],
    ]);
  });

  it("says what it calls while it runs, then how many steps ran", () => {
    const live = review(buildTimeline(subflowRunUntil(started("verdict")), parents).steps);
    expect(stepOutline(live)).toBe("Calling Checks · version 2");
    const done = review(buildTimeline(subflowRun.events, parents).steps);
    expect(stepOutline(done)).toBe("Called Checks · version 2 · 2 steps");
  });
});

describe("a subflow on the run map", () => {
  it("hangs the called workflow off its card, with how far it got", () => {
    const steps = buildTimeline(subflowRunUntil(started("verdict")), parents).steps;
    render(<RunMap spec={spec} steps={steps} onOpen={() => {}} now={0} />);
    const ids = screen.getAllByTestId("map-node").map((n) => n.getAttribute("data-node"));
    expect(ids).toEqual(["agent_1", "review", "review-agent_1", "verdict", "summary"]);
    expect(nodeStatuses(spec, steps).get("review")).toEqual({
      status: "running",
      summary: "1 of 2 steps",
    });
    expect(screen.getByText("1 of 2 steps")).toBeTruthy();
  });

  it("shows a called step inside its subflow", () => {
    const steps = buildTimeline(subflowRun.events, parents).steps;
    const focused = focusStep(steps, "verdict");
    expect(focused?.id).toBe("review");
    expect(focused?.subflow?.steps.map((s) => s.id)).toEqual(["verdict"]);
  });
});
