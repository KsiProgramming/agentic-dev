import { describe, expect, it } from "vitest";

import docsRun from "../fixtures/docs-run.json";
import docsSpec from "../fixtures/docs-run-spec.json";
import { runEvent } from "../testing";
import { buildTimeline } from "../timeline";
import type { RunEvent } from "../types";
import { focusStep, nodeStatuses } from "./node-status";
import type { WorkflowSpec } from "./spec-graph";

const spec = docsSpec as WorkflowSpec;
const events = docsRun as RunEvent[];

function event(
  seq: number,
  type: string,
  nodeId: string | null,
  payload: RunEvent["payload"] = {},
): RunEvent {
  return { ...runEvent(seq, type, payload), node_id: nodeId };
}

/** The docs run up to (and including) event `seq`. */
function upTo(seq: number) {
  return buildTimeline(events.filter((e) => e.seq <= seq)).steps;
}

describe("nodeStatuses", () => {
  it("marks every node not started before the run reaches it", () => {
    const states = nodeStatuses(spec, upTo(1));
    expect([...states.keys()]).toEqual([
      "list_modules",
      "document",
      "module-writer",
      "combine",
      "revise",
      "reviewer",
      "approve",
    ]);
    expect([...states.values()].every((s) => s.status === "not_started")).toBe(true);
  });

  it("follows the run: done, running, waiting", () => {
    const states = nodeStatuses(spec, upTo(84));
    expect(states.get("list_modules")?.status).toBe("completed");
    expect(states.get("document")).toEqual({ status: "completed", summary: "3 of 3 items" });
    expect(states.get("module-writer")?.status).toBe("completed");
    expect(states.get("revise")).toEqual({ status: "completed", summary: "Iteration 2 of 3" });
    expect(states.get("approve")).toEqual({ status: "waiting", summary: null });
  });

  it("counts a map's items while it runs", () => {
    const states = nodeStatuses(spec, upTo(25));
    expect(states.get("document")).toEqual({ status: "running", summary: "1 of 3 items" });
    // One item done, the next one running: the body node is running.
    expect(states.get("module-writer")?.status).toBe("running");
    expect(states.get("combine")?.status).toBe("not_started");
  });

  it("puts a failed item first on the map's body node and summary", () => {
    const steps = buildTimeline([
      event(1, "run_started", null),
      event(2, "node_started", "document", { items: 2 }),
      event(3, "map_item_started", "document", { index: 0, item: "a" }),
      event(4, "node_started", "module-writer", { item: 0 }),
      event(5, "node_completed", "module-writer", { item: 0 }),
      event(6, "map_item_completed", "document", { index: 0, status: "completed" }),
      event(7, "map_item_started", "document", { index: 1, item: "b" }),
      event(8, "node_started", "module-writer", { item: 1 }),
      event(9, "node_failed", "module-writer", { item: 1, error: "boom" }),
      event(10, "map_item_completed", "document", { index: 1, status: "failed" }),
    ]).steps;
    const states = nodeStatuses(spec, steps);
    expect(states.get("module-writer")?.status).toBe("failed");
    expect(states.get("document")?.summary).toBe("2 of 2 items · 1 failed");
  });

  it("takes the run's end for nodes cut off by it", () => {
    const steps = buildTimeline([
      event(1, "run_started", null),
      event(2, "node_started", "list_modules"),
      event(3, "run_cancelled", null, { reason: "cancelled by user" }),
    ]).steps;
    const states = nodeStatuses(spec, steps);
    expect(states.get("list_modules")?.status).toBe("cancelled");
    expect(states.get("document")?.status).toBe("not_started");
  });
});

describe("focusStep", () => {
  const steps = upTo(88);

  it("is a top-level node's own step", () => {
    expect(focusStep(steps, "list_modules")).toBe(steps[0]);
  });

  it("shows a map body node once per item, inside its map", () => {
    const focused = focusStep(steps, "module-writer")!;
    expect(focused.id).toBe("document");
    expect(focused.items?.map((i) => i.item)).toEqual(["packages/api", "packages/engine", "web"]);
    expect(focused.items?.every((i) => i.steps.map((s) => s.id).join() === "module-writer")).toBe(
      true,
    );
    expect(focused.turns).toEqual([]);
  });

  it("shows a loop body node once per iteration, inside its loop", () => {
    const focused = focusStep(steps, "reviewer")!;
    expect(focused.id).toBe("revise");
    expect(focused.iterations?.map((i) => [i.index, i.steps.map((s) => s.id)])).toEqual([
      [1, ["reviewer"]],
      [2, ["reviewer"]],
    ]);
  });

  it("keeps a map body node in its map when a budget stop names it without an item", () => {
    const stopped = buildTimeline([
      event(1, "run_started", null),
      event(2, "node_started", "document", { items: 1 }),
      event(3, "map_item_started", "document", { index: 0, item: "a" }),
      event(4, "node_started", "module-writer", { item: 0 }),
      event(5, "message", "module-writer", { item: 0, text: "Reading a." }),
      event(6, "node_cancelled", "module-writer", { item: 0 }),
      event(7, "policy_limit_exceeded", "module-writer", { limit: "budget_usd" }),
      event(8, "run_failed", null, { error: "policy limit: budget of $0.10 reached" }),
    ]).steps;

    const focused = focusStep(stopped, "module-writer")!;

    expect(focused.id).toBe("document");
    expect(focused.items?.[0]?.steps[0]?.turns).toHaveLength(1);
  });

  it("is null for a node that has not run", () => {
    expect(focusStep(upTo(5), "module-writer")).toBeNull();
    expect(focusStep(upTo(5), "approve")).toBeNull();
  });
});
