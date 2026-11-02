import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import { addStep, moveStep, newNode, removeStep, rootSteps, subtreeSize } from "./edits";
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
