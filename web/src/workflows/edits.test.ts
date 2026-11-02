import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import {
  addBranch,
  addStep,
  moveStep,
  moveTargets,
  moveTo,
  newNode,
  placeOf,
  removeStep,
  replaceNode,
  rootSteps,
  stayReason,
  subtreeSize,
} from "./edits";
import type { NodeManifest } from "./node-types";
import { applyOps } from "./ops";

const NODE_TYPES = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/node-types.json"), "utf8"),
) as NodeManifest[];

const agent = (id: string) => ({ type: "agent" as const, id, role: id, instructions: `Do ${id}.` });

const SPEC = {
  spec_version: "0",
  id: "flow",
  name: "Flow",
  root: {
    type: "sequence",
    id: "main",
    steps: [
      agent("a"),
      { type: "loop", id: "l", body: agent("agent_1"), until: "true", max_iterations: 2 },
      agent("c"),
    ],
  },
} as unknown as WorkflowSpec;

const ids = (spec: WorkflowSpec) => rootSteps(spec).map((s) => s.id);

describe("builder edits", () => {
  it("names a new node with the first free id of its kind, anywhere in the spec", () => {
    expect(newNode(SPEC, "agent", NODE_TYPES).id).toBe("agent_2");
    expect(newNode(SPEC, "gate", NODE_TYPES)).toEqual({
      type: "gate",
      id: "gate_1",
      title: "Approve",
    });
  });

  it("gives every node of a container a fresh id, and leaves route ids alone", () => {
    const router = newNode(SPEC, "router", NODE_TYPES) as unknown as {
      id: string;
      routes: { id: string; then: { id: string } }[];
      default: { id: string };
    };
    expect(router.id).toBe("router_1");
    expect(router.routes[0].id).toBe("match");
    expect([router.routes[0].then.id, router.default.id]).toEqual(["agent_2", "agent_3"]);
    const parallel = applyOps(SPEC, addStep(SPEC, "c", "parallel", NODE_TYPES).ops);
    expect(ids(parallel)).toEqual(["a", "l", "c", "parallel_1"]);
  });

  it("fills a reduce's source with the step it is added after", () => {
    expect(newNode(SPEC, "reduce", NODE_TYPES, "c")).toMatchObject({ id: "reduce_1", from: "c" });
  });

  it("adds a kind it only knows from its manifest", () => {
    const echo: NodeManifest = {
      kind: "echo",
      label: "Echo",
      description: "Says its text back.",
      category: "step",
      icon: "megaphone",
      parameters: {},
      slots: [],
      default: { type: "echo", id: "echo", text: "hi" },
      fill: {},
    };
    const edit = addStep(SPEC, "a", "echo", [...NODE_TYPES, echo]);
    expect(edit.ops).toEqual([
      { op: "addNode", node: { type: "echo", id: "echo_1", text: "hi" }, at: { after: "a" } },
    ]);
    expect(() => newNode(SPEC, "nope", NODE_TYPES)).toThrow("There is no node type nope.");
  });

  it("adds a step after another, or first", () => {
    const add = (after: string | null, kind: string) =>
      ids(applyOps(SPEC, addStep(SPEC, after, kind, NODE_TYPES).ops));
    expect(add("a", "tool")).toEqual(["a", "tool_1", "l", "c"]);
    expect(add(null, "gate")).toEqual(["gate_1", "a", "l", "c"]);
  });

  it("moves a step with one connect, at either end too", () => {
    const moved = (id: string, d: "up" | "down") => {
      const edit = moveStep(SPEC, id, d);
      expect(edit?.ops).toHaveLength(1);
      return ids(applyOps(SPEC, edit!.ops));
    };
    expect(moved("a", "down")).toEqual(["l", "a", "c"]);
    expect(moved("l", "up")).toEqual(["l", "a", "c"]);
    expect(moved("c", "up")).toEqual(["a", "c", "l"]);
    expect(moveStep(SPEC, "a", "up")).toBeNull();
    expect(moveStep(SPEC, "c", "down")).toBeNull();
    expect(moveStep(SPEC, "agent_1", "up")).toBeNull();
  });

  it("removes a step with what is under it", () => {
    expect(ids(applyOps(SPEC, removeStep("l").ops))).toEqual(["a", "c"]);
    expect(subtreeSize(rootSteps(SPEC)[1])).toBe(2);
  });
});

// A spec with every kind of slot: a map's lone body, a parallel of three branches (one a
// sequence), a loop whose body is a sequence, a router with a route and a default.
const NESTED = {
  spec_version: "0",
  id: "nested",
  name: "Nested",
  root: {
    type: "sequence",
    id: "main",
    steps: [
      agent("a"),
      { type: "map", id: "m", over: "items", body: agent("each"), max_concurrency: 2 },
      {
        type: "parallel",
        id: "p",
        join: "all",
        branches: [
          agent("b1"),
          { type: "sequence", id: "s2", steps: [agent("b2"), agent("b2_next")] },
          agent("b3"),
        ],
      },
      {
        type: "loop",
        id: "l",
        until: "true",
        max_iterations: 2,
        body: { type: "sequence", id: "ls", steps: [agent("x"), agent("y")] },
      },
      {
        type: "router",
        id: "r",
        routes: [{ id: "fix", when: "true", then: agent("fixer") }],
        default: agent("fallback"),
      },
    ],
  },
} as unknown as WorkflowSpec;

const at = (spec: WorkflowSpec, id: string) => placeOf(spec, id);

describe("nested edits (5.5)", () => {
  it("finds where a node is", () => {
    expect(at(NESTED, "main")).toMatchObject({ slot: "root", parent: null });
    expect(at(NESTED, "each")).toMatchObject({ slot: "body", parent: { id: "m" } });
    expect(at(NESTED, "b3")).toMatchObject({
      slot: "branches",
      index: 2,
      siblings: ["b1", "s2", "b3"],
    });
    expect(at(NESTED, "y")).toMatchObject({ slot: "steps", index: 1, parent: { id: "ls" } });
    expect(at(NESTED, "fixer")).toMatchObject({ slot: "route", route: "fix" });
    expect(at(NESTED, "fallback")).toMatchObject({ slot: "route", route: "default" });
    expect(at(NESTED, "nope")).toBeNull();
  });

  it("says why a node cannot leave its place, and lets the rest go", () => {
    const reason = (id: string) => stayReason(at(NESTED, id)!);
    expect(reason("main")).toBe("The workflow's root stays.");
    expect(reason("each")).toBe("A map needs a body; replace it instead.");
    expect(reason("fixer")).toBe("A route needs a step; replace it instead.");
    expect([reason("fallback"), reason("b1"), reason("x"), reason("a")]).toEqual([
      null,
      null,
      null,
      null,
    ]);
    const two = applyOps(NESTED, removeStep("b3").ops);
    expect(stayReason(placeOf(two, "b1")!)).toBe("A parallel needs at least two branches.");
    const one = applyOps(NESTED, removeStep("y").ops);
    expect(stayReason(placeOf(one, "x")!)).toBe("The only step here stays; replace it instead.");
  });

  it("adds after a nested step in its sequence, and wraps a lone node in a new sequence", () => {
    const inLoop = addStep(NESTED, "x", "gate", NODE_TYPES);
    expect(inLoop.ops).toEqual([
      { op: "addNode", node: expect.objectContaining({ id: "gate_1" }), at: { after: "x" } },
    ]);
    expect(placeOf(applyOps(NESTED, inLoop.ops), "gate_1")?.siblings).toEqual(["x", "gate_1", "y"]);

    const inMap = addStep(NESTED, "each", "agent", NODE_TYPES);
    expect(inMap.ops[1]).toEqual({
      op: "connect",
      from: "each",
      to: "agent_1",
      sequence_id: "sequence_1",
    });
    const body = placeOf(applyOps(NESTED, inMap.ops), "each")!;
    expect(body).toMatchObject({ slot: "steps", parent: { id: "sequence_1" } });
    expect(body.siblings).toEqual(["each", "agent_1"]);
    expect(inMap.focus).toBe("agent_1");

    const onRoute = applyOps(NESTED, addStep(NESTED, "fixer", "gate", NODE_TYPES).ops);
    expect(placeOf(onRoute, "sequence_1")).toMatchObject({ slot: "route", route: "fix" });
  });

  it("adds a branch to a parallel", () => {
    const spec = applyOps(NESTED, addBranch(NESTED, "p", "agent", NODE_TYPES).ops);
    expect(placeOf(spec, "agent_1")?.siblings).toEqual(["b1", "s2", "b3", "agent_1"]);
  });

  it("moves a nested step within its own sequence only", () => {
    const down = moveStep(NESTED, "x", "down")!;
    expect(placeOf(applyOps(NESTED, down.ops), "x")?.siblings).toEqual(["y", "x"]);
    expect(moveStep(NESTED, "b2_next", "up")?.ops).toEqual([
      { op: "connect", from: "b2_next", to: "b2" },
    ]);
    expect(moveStep(NESTED, "each", "down")).toBeNull();
    expect(moveStep(NESTED, "b1", "down")).toBeNull();
  });

  it("lists where a node can move, and moves it there with what is under it", () => {
    const after = (id: string) =>
      moveTargets(NESTED, id).flatMap((t) => ("after" in t ? [t.after] : []));
    const branches = (id: string) =>
      moveTargets(NESTED, id).flatMap((t) => ("branchOf" in t ? [t.branchOf] : []));
    // Not itself or under it, not a sequence, not right after the step before it.
    expect(after("l")).toEqual([
      "a",
      "m",
      "each",
      "b1",
      "b2",
      "b2_next",
      "b3",
      "r",
      "fixer",
      "fallback",
    ]);
    expect(branches("l")).toEqual(["p"]);
    expect(branches("b1")).toEqual([]);
    expect(moveTargets(NESTED, "each")).toEqual([]);
    expect(moveTargets(NESTED, "main")).toEqual([]);

    const out = applyOps(NESTED, moveTo(NESTED, "b3", { after: "a" }).ops);
    expect(rootSteps(out).map((s) => s.id)).toEqual(["a", "b3", "m", "p", "l", "r"]);
    expect(placeOf(out, "b1")?.siblings).toEqual(["b1", "s2"]);

    const intoMap = moveTo(NESTED, "a", { after: "each" });
    expect(intoMap.ops).toEqual([
      { op: "connect", from: "each", to: "a", sequence_id: "sequence_1" },
    ]);
    expect(placeOf(applyOps(NESTED, intoMap.ops), "a")?.siblings).toEqual(["each", "a"]);

    const branch = moveTo(NESTED, "l", { branchOf: "p" });
    const moved = applyOps(NESTED, branch.ops);
    expect(placeOf(moved, "l")).toMatchObject({ slot: "branches", index: 3 });
    expect(placeOf(moved, "y")?.parent?.id).toBe("ls");
  });

  it("replaces a lone body, a route and a branch so no container is ever empty", () => {
    const body = replaceNode(NESTED, "each", "tool", NODE_TYPES)!;
    expect(body.ops).toEqual([
      { op: "removeNode", node_id: "each" },
      { op: "addNode", node: expect.objectContaining({ id: "tool_1" }), at: { parent: "m" } },
    ]);
    expect(placeOf(applyOps(NESTED, body.ops), "tool_1")?.slot).toBe("body");

    const route = applyOps(NESTED, replaceNode(NESTED, "fixer", "gate", NODE_TYPES)!.ops);
    expect(placeOf(route, "gate_1")).toMatchObject({ slot: "route", route: "fix" });
    const fallback = applyOps(NESTED, replaceNode(NESTED, "fallback", "gate", NODE_TYPES)!.ops);
    expect(placeOf(fallback, "gate_1")).toMatchObject({ slot: "route", route: "default" });

    const branch = applyOps(NESTED, replaceNode(NESTED, "s2", "agent", NODE_TYPES)!.ops);
    expect(placeOf(branch, "agent_1")?.siblings).toEqual(["b1", "agent_1", "b3"]);

    const reduce = replaceNode(NESTED, "y", "reduce", NODE_TYPES)!;
    expect(reduce.ops[1]).toMatchObject({ node: { from: "x" }, at: { parent: "ls", index: 1 } });
    expect(replaceNode(NESTED, "main", "agent", NODE_TYPES)).toBeNull();
  });
});
