import { describe, expect, it } from "vitest";

import docsRun from "../fixtures/docs-run.json";
import docsSpec from "../fixtures/docs-run-spec.json";
import { runEvent } from "../testing";
import { buildTimeline, type Step } from "../timeline";
import type { RunEvent } from "../types";
import { focusStep, nodeStatuses, routeStates } from "./node-status";
import { routeNodeId, type WorkflowSpec } from "./spec-graph";

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
/** Where the recorded run pauses at its gate. */
const GATE_WAITING = events.find((e) => e.type === "gate_waiting")!.seq;

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
    const states = nodeStatuses(spec, upTo(GATE_WAITING));
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

describe("a parallel", () => {
  const parallelSpec: WorkflowSpec = {
    spec_version: "0",
    id: "p",
    name: "P",
    root: {
      type: "parallel",
      id: "review",
      join: "any",
      branches: ["fast", "slow", "broken"].map((id) => ({
        type: "agent" as const,
        id,
        role: "R",
        instructions: "Go.",
        tools: [],
      })),
    },
  };
  const steps = buildTimeline([
    event(1, "node_started", "review", { branches: 3, join: "any" }),
    event(2, "parallel_branch_started", "review", { index: 0, branch_id: "fast" }),
    event(3, "parallel_branch_started", "review", { index: 1, branch_id: "slow" }),
    event(4, "parallel_branch_started", "review", { index: 2, branch_id: "broken" }),
    event(5, "node_started", "fast", { branch: 0 }),
    event(6, "node_started", "slow", { branch: 1 }),
    event(7, "node_started", "broken", { branch: 2 }),
    event(8, "node_failed", "broken", { branch: 2, error: "model refused" }),
    event(9, "parallel_branch_completed", "review", {
      index: 2,
      branch_id: "broken",
      status: "failed",
    }),
    event(10, "node_completed", "fast", { branch: 0 }),
    event(11, "node_cancelled", "slow", { branch: 1 }),
    event(12, "parallel_branch_completed", "review", {
      index: 0,
      branch_id: "fast",
      status: "completed",
    }),
    event(13, "parallel_branch_completed", "review", {
      index: 1,
      branch_id: "slow",
      status: "cancelled",
    }),
    event(14, "node_completed", "review"),
  ]).steps;

  it("says how its branches went, and each branch node has its own status", () => {
    const states = nodeStatuses(parallelSpec, steps);
    expect(states.get("review")).toEqual({
      status: "completed",
      summary: "3 of 3 branches · any · 1 failed · 1 cancelled",
    });
    expect(states.get("fast")?.status).toBe("completed");
    expect(states.get("slow")?.status).toBe("cancelled");
    expect(states.get("broken")?.status).toBe("failed");
  });

  it("shows a branch node inside its parallel, with only that branch", () => {
    const focused = focusStep(steps, "slow");
    expect(focused?.id).toBe("review");
    expect(focused?.branches?.map((b) => b.id)).toEqual(["slow"]);
    expect(focused?.branches?.[0]!.steps.map((s) => s.id)).toEqual(["slow"]);
  });
});

describe("router statuses (4.6)", () => {
  const agent = (id: string): WorkflowSpec["root"] => ({
    type: "agent",
    id,
    role: "R",
    instructions: "go",
    tools: [],
  });
  const routed: WorkflowSpec = {
    spec_version: "0",
    id: "w",
    name: "W",
    root: {
      type: "router",
      id: "report_path",
      routes: [
        { id: "clean", when: "true", then: agent("clean_report") },
        {
          id: "fix_first",
          when: "true",
          then: { type: "sequence", id: "fix", steps: [agent("plan"), agent("fix_report")] },
        },
      ],
      default: agent("standard_report"),
    },
  };

  /** The router's step: started, with `chosen` and the steps of its route. */
  function routerStep(chosen: string | null, routeSteps: RunEvent[] = []): Step {
    const [step] = buildTimeline([event(1, "node_started", "report_path")]).steps;
    const inner = buildTimeline(routeSteps).steps;
    return {
      ...step!,
      router: {
        routes: ["clean", "fix_first", "default"],
        mode: "rule",
        chosen,
        reason: null,
        steps: inner,
      },
    };
  }

  it("says the router is choosing until it chose, and nothing is skipped yet", () => {
    const states = nodeStatuses(routed, [routerStep(null)]);
    expect(states.get("report_path")).toEqual({ status: "running", summary: "Choosing a route" });
    expect(states.get("plan")?.status).toBe("not_started");
    expect([...routeStates(routed, [routerStep(null)]).values()].map((s) => s.status)).toEqual([
      "not_started",
      "not_started",
      "not_started",
    ]);
  });

  it("skips the routes not taken, and the taken route's nodes follow their steps", () => {
    const steps = [routerStep("fix_first", [event(2, "node_started", "plan")])];
    const states = nodeStatuses(routed, steps);
    expect(states.get("report_path")?.summary).toBe("Routed to fix_first");
    expect(states.get("plan")?.status).toBe("running");
    expect(states.get("fix_report")?.status).toBe("not_started");
    expect(states.get("clean_report")?.status).toBe("skipped");
    expect(states.get("standard_report")?.status).toBe("skipped");
    expect(states.has(routeNodeId("report_path", "clean"))).toBe(false);
    const routes = routeStates(routed, steps);
    expect(routes.get(routeNodeId("report_path", "clean"))?.status).toBe("skipped");
    expect(routes.get(routeNodeId("report_path", "fix_first"))?.status).toBe("not_started");
    expect(routes.get(routeNodeId("report_path", "default"))?.status).toBe("skipped");
  });

  it("keeps a route that any run took (a router in a map)", () => {
    const steps = [routerStep("clean"), routerStep("default")];
    const states = nodeStatuses(routed, steps);
    expect(states.get("report_path")?.summary).toBe("Routed to clean, default");
    expect(states.get("plan")?.status).toBe("skipped");
    expect(states.get("standard_report")?.status).toBe("not_started");
  });

  it("finds a step that ran on a route", () => {
    const steps = [routerStep("fix_first", [event(2, "node_started", "plan")])];
    const focused = focusStep(steps, "plan");
    expect(focused?.id).toBe("report_path");
    expect(focused?.router?.steps.map((s) => s.id)).toEqual(["plan"]);
    expect(focused?.turns).toEqual([]);
  });
});
