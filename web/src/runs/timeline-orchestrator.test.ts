import { describe, expect, it } from "vitest";

import { orchestratorRun, orchestratorRunUntil } from "./fixtures/orchestrator-run";
import { specParents } from "./spec-parents";
import { buildTimeline, stepUsage, type Step } from "./timeline";

const parents = specParents(orchestratorRun.spec.root);

function fix(steps: Step[]): Step {
  const step = steps.find((s) => s.id === "fix");
  if (!step?.orchestrator) throw new Error("no orchestrator step");
  return step;
}

function tasks(step: Step) {
  return step.orchestrator!.tasks.map((t) => [t.id, t.round, t.status, t.error]);
}

describe.each([
  ["with the spec", parents],
  ["from the tags alone", null],
])("an orchestrator's tasks (%s)", (_, known) => {
  const timeline = buildTimeline(orchestratorRun.events, known);

  it("are listed under it, by round, with how each ended", () => {
    const step = fix(timeline.steps);
    expect(timeline.steps.map((s) => s.id)).toEqual(["scan", "fix"]);
    expect(step.status).toBe("completed");
    expect(tasks(step)).toEqual([
      ["a", 1, "completed", null],
      ["b", 1, "failed", "fixer failed: cannot fix b"],
      ["c", 1, "failed", "conflicts with earlier tasks on src/app.py"],
      ["d", 1, "dropped", null],
      ["b2", 2, "completed", null],
      ["c2", 2, "completed", null],
    ]);
    expect(step.orchestrator!.tasks.find((t) => t.id === "c")!.conflict).toEqual(["src/app.py"]);
  });

  it("put each worker's steps in its task", () => {
    const step = fix(timeline.steps);
    for (const task of step.orchestrator!.tasks) {
      const ran = task.status !== "dropped";
      expect(task.steps.map((s) => s.id)).toEqual(ran ? ["fixer"] : []);
    }
    const b = step.orchestrator!.tasks.find((t) => t.id === "b")!;
    expect(b.steps[0]!.status).toBe("failed");
    const a = step.orchestrator!.tasks.find((t) => t.id === "a")!;
    expect(a.steps[0]!.turns.map((t) => t.kind)).toEqual(["tool", "message"]);
  });

  it("keep the hub's turns as the orchestrator's own", () => {
    const step = fix(timeline.steps);
    expect(step.turns.filter((t) => t.kind === "message")).toHaveLength(2);
    expect(step.usage?.inputTokens).toBe(20);
  });

  it("record each round's plan, reason, replan and integration", () => {
    const { rounds, maxWorkers } = fix(timeline.steps).orchestrator!;
    expect(maxWorkers).toBe(6);
    expect(rounds).toHaveLength(2);
    expect(rounds[0]).toMatchObject({
      round: 1,
      taskIds: ["a", "b", "c", "d"],
      reason: "One task per module.",
      replan: null,
      integration: {
        branch: "agent/run/fix",
        merged: ["a"],
        conflicts: [{ id: "c", paths: ["src/app.py"] }],
      },
    });
    expect(rounds[1]).toMatchObject({
      round: 2,
      taskIds: ["b2", "c2"],
      reason: "Retry b and c apart from a.",
      replan: {
        failed: [
          { id: "b", error: "fixer failed: cannot fix b" },
          { id: "c", error: "conflicts with earlier tasks on src/app.py" },
        ],
        dropped: ["d"],
      },
      integration: { merged: ["a", "b2", "c2"], conflicts: [] },
    });
  });

  it("add the hub and every task to what the orchestrator cost", () => {
    const usage = stepUsage(fix(timeline.steps));
    // Two hub turns and the four workers that answered (b failed first), 10 tokens each.
    expect(usage?.inputTokens).toBe(60);
    expect(usage?.estimatedUsd).toBeCloseTo(0.0006);
  });
});

describe("an orchestrator while it runs", () => {
  const seqOf = (type: string, nth = 0) =>
    orchestratorRun.events.filter((e) => e.type === type && e.node_id === "fix")[nth]!.seq;

  it("is planning before its plan", () => {
    const step = fix(buildTimeline(orchestratorRunUntil(seqOf("plan_made") - 1), parents).steps);
    expect(step.status).toBe("running");
    expect(step.orchestrator!.tasks).toEqual([]);
  });

  it("lists every planned task at once, pending until it starts", () => {
    const step = fix(buildTimeline(orchestratorRunUntil(seqOf("plan_made")), parents).steps);
    expect(tasks(step).map(([id, , status]) => [id, status])).toEqual([
      ["a", "pending"],
      ["b", "pending"],
      ["c", "pending"],
      ["d", "pending"],
    ]);
  });

  it("shows tasks running with what they cost so far", () => {
    const firstUsage = orchestratorRun.events.find(
      (e) => e.type === "usage" && e.node_id === "fixer",
    )!.seq;
    const step = fix(buildTimeline(orchestratorRunUntil(firstUsage), parents).steps);
    const [a, b, c, d] = step.orchestrator!.tasks;
    expect([a!.status, b!.status, c!.status, d!.status]).toEqual([
      "running",
      "failed",
      "running",
      "dropped",
    ]);
    expect(stepUsage(a!.steps[0]!)?.inputTokens).toBe(10);
    expect(c!.steps[0]!.usage).toBeNull();
  });

  it("cancels tasks never started when the run ends", () => {
    const cut = [
      ...orchestratorRunUntil(seqOf("plan_made")),
      {
        ...orchestratorRun.events.at(-1)!,
        seq: 1000,
        type: "run_failed",
        payload: {},
      },
    ];
    const step = fix(buildTimeline(cut, parents).steps);
    expect(step.status).toBe("failed");
    expect(step.orchestrator!.tasks.every((t) => t.status === "cancelled")).toBe(true);
  });
});
