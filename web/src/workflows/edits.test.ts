import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import {
  addStep,
  moveStep,
  newNode,
  removeStep,
  rootSteps,
  setDocument,
  subtreeSize,
} from "./edits";
import { applyOps } from "./ops";

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
    expect(newNode(SPEC, "agent").id).toBe("agent_2");
    expect(newNode(SPEC, "gate")).toEqual({ type: "gate", id: "gate_1", title: "Approve" });
  });

  it("adds a step after another, or first", () => {
    expect(ids(applyOps(SPEC, addStep(SPEC, "a", "tool").ops))).toEqual(["a", "tool_1", "l", "c"]);
    expect(ids(applyOps(SPEC, addStep(SPEC, null, "gate").ops))).toEqual(["gate_1", "a", "l", "c"]);
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

  it("sets the name, and unsets an empty description", () => {
    expect(applyOps(SPEC, setDocument("name", "New").ops).name).toBe("New");
    const withDescription = { ...SPEC, description: "Old" };
    expect(applyOps(withDescription, setDocument("description", " ").ops)).not.toHaveProperty(
      "description",
    );
  });
});
