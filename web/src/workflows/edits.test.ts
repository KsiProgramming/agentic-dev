import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import {
  addBranch,
  addStep,
  blockReason,
  extractNodes,
  laterSteps,
  moveStep,
  moveTargets,
  moveTo,
  newMismatches,
  newNode,
  pendingExtracts,
  placeOf,
  rangeOf,
  removeStep,
  replaceNode,
  rootSteps,
  stayReason,
  subtreeSize,
  updateCall,
  wrapNodes,
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

describe("blocked connections (5.6)", () => {
  // `a` gives `a`, `b` gives `b`, `c` needs `b` and gives `c`, and `d` needs `a`, which `c` does
  // not give: the spec already has one mismatch, on `d`.
  const obj = (props: string[], required: string[] = []) => ({
    type: "object",
    properties: Object.fromEntries(props.map((p) => [p, { type: "string" }])),
    required,
  });
  const TYPED = {
    spec_version: "0",
    id: "flow",
    name: "Flow",
    root: {
      type: "sequence",
      id: "main",
      steps: [
        { ...agent("a"), output_schema: obj(["a"]) },
        { ...agent("b"), output_schema: obj(["b"]) },
        { ...agent("c"), input_schema: obj(["b"], ["b"]), output_schema: obj(["c"]) },
        { ...agent("d"), input_schema: obj(["a"], ["a"]) },
      ],
    },
  } as unknown as WorkflowSpec;
  const C_NEEDS_B =
    "The input_schema of 'c' requires 'b', which the output_schema of 'a' does not declare.";

  it("blocks each structural edit that connects ports that do not fit", () => {
    expect(blockReason(TYPED, removeStep("b"))).toBe(C_NEEDS_B);
    expect(blockReason(TYPED, moveStep(TYPED, "c", "up"))).toBe(C_NEEDS_B);
    expect(blockReason(TYPED, moveStep(TYPED, "a", "down"))).toBe(C_NEEDS_B);
    expect(blockReason(TYPED, moveTo(TYPED, "c", { after: "a" }))).toBe(C_NEEDS_B);
    expect(newMismatches(TYPED, removeStep("b"))).toEqual([
      expect.objectContaining({ producer: "a", consumer: "c" }),
    ]);
  });

  it("allows an edit that breaks an edge, keeps a mismatch or removes one", () => {
    expect(blockReason(TYPED, replaceNode(TYPED, "b", "agent", NODE_TYPES))).toBeNull();
    expect(blockReason(TYPED, addStep(TYPED, "a", "agent", NODE_TYPES))).toBeNull();
    // `d`'s mismatch is there already: an edit elsewhere keeps it, and removing `d` drops it.
    expect(newMismatches(TYPED, replaceNode(TYPED, "b", "agent", NODE_TYPES)!)).toEqual([]);
    expect(blockReason(TYPED, removeStep("d"))).toBeNull();
    expect(blockReason(TYPED, null)).toBeNull();
  });

  it("finds nothing new for an edit that does not apply", () => {
    expect(newMismatches(TYPED, removeStep("nope"))).toEqual([]);
  });
});

describe("an orchestrator's worker on the canvas (6.4)", () => {
  const ORCHESTRATED = {
    spec_version: "0",
    id: "flow",
    name: "Flow",
    root: {
      type: "sequence",
      id: "main",
      steps: [
        agent("a"),
        {
          type: "orchestrator",
          id: "fix",
          hub: { role: "Lead", instructions: "Plan." },
          body: agent("fixer"),
          max_workers: 4,
          max_concurrency: 2,
        },
        agent("c"),
      ],
    },
  } as unknown as WorkflowSpec;

  it("is the orchestrator's body, which stays", () => {
    const place = placeOf(ORCHESTRATED, "fixer")!;
    expect(place).toMatchObject({ slot: "body", parent: { id: "fix" } });
    expect(stayReason(place)).toBe("An orchestrator needs a body; replace it instead.");
    expect(moveTargets(ORCHESTRATED, "fixer")).toEqual([]);
  });

  it("can be replaced, and grows into a sequence when a step is added after it", () => {
    const replaced = applyOps(
      ORCHESTRATED,
      replaceNode(ORCHESTRATED, "fixer", "agent", NODE_TYPES)!.ops,
    );
    expect(placeOf(replaced, "agent_1")).toMatchObject({ slot: "body", parent: { id: "fix" } });
    const grown = applyOps(ORCHESTRATED, addStep(ORCHESTRATED, "fixer", "tool", NODE_TYPES).ops);
    const body = placeOf(grown, "sequence_1")!;
    expect(body).toMatchObject({ slot: "body", parent: { id: "fix" } });
    expect(
      blockReason(ORCHESTRATED, addStep(ORCHESTRATED, "fixer", "agent", NODE_TYPES)),
    ).toBeNull();
  });

  it("refuses what a worker may not hold, with the reason", () => {
    expect(blockReason(ORCHESTRATED, addStep(ORCHESTRATED, "fixer", "gate", NODE_TYPES))).toBe(
      "The worker of 'fix' holds only agents and tools, not a gate.",
    );
    expect(blockReason(ORCHESTRATED, replaceNode(ORCHESTRATED, "fixer", "loop", NODE_TYPES))).toBe(
      "The worker of 'fix' holds only agents and tools, not a loop.",
    );
    // A gate after the orchestrator, outside its worker, is fine.
    expect(blockReason(ORCHESTRATED, addStep(ORCHESTRATED, "fix", "gate", NODE_TYPES))).toBeNull();
  });
});

describe("composite edits (6.6)", () => {
  const FLOW = {
    ...SPEC,
    root: {
      type: "sequence",
      id: "main",
      steps: [agent("a"), agent("b"), agent("c"), agent("subflow_1")],
    },
  } as unknown as WorkflowSpec;

  it("ranges run from a step through a later one of its sequence", () => {
    expect(laterSteps(FLOW, "b")).toEqual(["c", "subflow_1"]);
    expect(laterSteps(SPEC, "agent_1")).toEqual([]);
    expect(rangeOf(FLOW, "a", "c")).toEqual(["a", "b", "c"]);
    expect(rangeOf(FLOW, "b", null)).toEqual(["b"]);
    expect(rangeOf(FLOW, "c", "a")).toEqual(["c"]);
  });

  it("wraps steps in a container from its manifest, without the nodes it holds", () => {
    const edit = wrapNodes(FLOW, ["a", "b"], "loop", NODE_TYPES);
    expect(edit.ops).toEqual([
      {
        op: "wrap",
        node_ids: ["a", "b"],
        with: { type: "loop", id: "loop_1", until: expect.any(String), max_iterations: 3 },
        sequence_id: "sequence_1",
      },
    ]);
    expect(edit.focus).toBe("loop_1");
    const wrapped = applyOps(FLOW, edit.ops);
    expect(ids(wrapped)).toEqual(["loop_1", "c", "subflow_1"]);
    // One node needs no sequence; a sequence takes the steps as they are.
    expect(wrapNodes(FLOW, ["c"], "map", NODE_TYPES).ops[0]).not.toHaveProperty("sequence_id");
    const sequence = applyOps(FLOW, wrapNodes(FLOW, ["b", "c"], "sequence", NODE_TYPES).ops);
    expect(ids(sequence)).toEqual(["a", "sequence_1", "subflow_1"]);
  });

  it("extracts steps into a workflow called in their place, under a fresh id", () => {
    const edit = extractNodes(FLOW, ["b", "c"], { id: "review", name: "Review" });
    expect(edit.ops).toEqual([
      {
        op: "extract",
        node_ids: ["b", "c"],
        subflow_id: "subflow_2",
        workflow: { id: "review", name: "Review" },
      },
    ]);
    expect(ids(applyOps(FLOW, edit.ops))).toEqual(["a", "subflow_2", "subflow_1"]);
    // An extracted node's id is free once it has moved.
    const own = extractNodes(FLOW, ["subflow_1"], { id: "w", name: "W", description: "D." });
    expect(own.ops[0]).toMatchObject({ subflow_id: "subflow_1", workflow: { description: "D." } });
    expect(pendingExtracts([edit, removeStep("a")])).toEqual(new Set(["review"]));
  });

  it("moves a call to a newer version with one setParam", () => {
    expect(updateCall("check", 3)).toEqual({
      label: "Update check to version 3",
      focus: "check",
      ops: [{ op: "setParam", node_id: "check", path: "workflow.version", value: 3 }],
    });
  });

  it("adds a composite from its palette entry, pinned to its published version", () => {
    const subflow = NODE_TYPES.find((m) => m.kind === "subflow")!;
    const composite = {
      ...subflow,
      label: "Review",
      category: "workspace",
      composite: { workflow_id: "review", version: 2 },
      default: { type: "subflow", id: "subflow", workflow: { id: "review", version: 2 } },
    } as NodeManifest;
    const node = newNode(FLOW, "composite:review", [...NODE_TYPES, composite]);
    expect(node).toEqual({
      type: "subflow",
      id: "subflow_2",
      workflow: { id: "review", version: 2 },
    });
    // The primitive keeps its own default.
    expect(newNode(FLOW, "subflow", [...NODE_TYPES, composite])).toMatchObject({
      workflow: { id: "workflow", version: 1 },
    });
  });
});
