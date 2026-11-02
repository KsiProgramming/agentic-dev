import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type { SpecNode, WorkflowSpec } from "@/runs/graph/spec-graph";

import type { NodeManifest } from "./node-types";
import { applyOps } from "./ops";
import { documentParams, nodeParams, paramEdit, paramOps, type Schema } from "./params";

const NODE_TYPES = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/node-types.json"), "utf8"),
) as NodeManifest[];
const manifest = (kind: string) => NODE_TYPES.find((m) => m.kind === kind)!;
const schemaOf = (kind: string) => manifest(kind).parameters as Schema;

const AGENT = { type: "agent", id: "a", role: "Writer", instructions: "Write.", tools: [] };
const ROUTER = {
  type: "router",
  id: "r",
  routes: [
    { id: "one", when: "true", then: { type: "agent", id: "r1", role: "r", instructions: "R." } },
    { id: "two", when: "false", then: { type: "agent", id: "r2", role: "r", instructions: "R." } },
  ],
};

describe("nodeParams", () => {
  it("leaves out the type, the id and what holds nodes", () => {
    expect(nodeParams(AGENT as unknown as SpecNode, manifest("agent"))).toEqual({
      role: "Writer",
      instructions: "Write.",
      tools: [],
    });
    expect(nodeParams(ROUTER as unknown as SpecNode, manifest("router"))).toEqual({
      routes: [
        { id: "one", when: "true" },
        { id: "two", when: "false" },
      ],
    });
  });
});

describe("paramOps", () => {
  const agent = nodeParams(AGENT as unknown as SpecNode, manifest("agent"));

  it("sets a changed field", () => {
    expect(paramOps("a", agent, { ...agent, role: "Editor" }, schemaOf("agent"))).toEqual([
      { op: "setParam", node_id: "a", path: "role", value: "Editor" },
    ]);
  });

  it("sets a list of tools whole", () => {
    const after = { ...agent, tools: ["repo.read_file", "repo.search"] };
    expect(paramOps("a", agent, after, schemaOf("agent"))).toEqual([
      { op: "setParam", node_id: "a", path: "tools", value: ["repo.read_file", "repo.search"] },
    ]);
  });

  it("unsets a cleared optional field, and does nothing when nothing changed", () => {
    const withModel = { ...agent, model: "claude-x" };
    expect(paramOps("a", withModel, { ...agent, model: undefined }, schemaOf("agent"))).toEqual([
      { op: "setParam", node_id: "a", path: "model", value: null },
    ]);
    expect(paramOps("a", agent, { ...agent, model: "" }, schemaOf("agent"))).toEqual([]);
    expect(paramOps("a", agent, structuredClone(agent), schemaOf("agent"))).toEqual([]);
  });

  it("sets a port schema whole", () => {
    const port = { type: "object", properties: { n: { type: "number" } } };
    expect(paramOps("a", agent, { ...agent, output_schema: port }, schemaOf("agent"))).toEqual([
      { op: "setParam", node_id: "a", path: "output_schema", value: port },
    ]);
  });

  it("sets a route's field by its index", () => {
    const before = nodeParams(ROUTER as unknown as SpecNode, manifest("router"));
    const after = {
      routes: [
        { id: "one", when: "true" },
        { id: "two", when: "last == 'x'" },
      ],
    };
    expect(paramOps("r", before, after, schemaOf("router"))).toEqual([
      { op: "setParam", node_id: "r", path: "routes[1].when", value: "last == 'x'" },
    ]);
  });

  it("enters a classifier that is set, and sets one that was not whole", () => {
    const before = nodeParams(ROUTER as unknown as SpecNode, manifest("router"));
    const classifier = { instructions: "Pick one." };
    const added = paramOps("r", before, { ...before, classifier }, schemaOf("router"));
    expect(added).toEqual([
      { op: "setParam", node_id: "r", path: "classifier", value: classifier },
    ]);

    const withClassifier = { ...before, classifier };
    const changed = { ...before, classifier: { instructions: "Pick the best." } };
    expect(paramOps("r", withClassifier, changed, schemaOf("router"))).toEqual([
      { op: "setParam", node_id: "r", path: "classifier.instructions", value: "Pick the best." },
    ]);
  });

  it("makes ops the engine's mirror applies", () => {
    const spec = {
      spec_version: "0",
      id: "flow",
      name: "Flow",
      root: { type: "sequence", id: "main", steps: [AGENT, ROUTER] },
    } as unknown as WorkflowSpec;
    const before = nodeParams(ROUTER as unknown as SpecNode, manifest("router"));
    const after = { ...before, classifier: { instructions: "Pick." } };
    const next = applyOps(spec, paramOps("r", before, after, schemaOf("router")));
    expect((next.root as { steps: unknown[] }).steps[1]).toMatchObject({
      classifier: { instructions: "Pick." },
    });
  });
});

describe("paramEdit", () => {
  const SPEC = {
    spec_version: "0",
    id: "flow",
    name: "Flow",
    root: AGENT,
  } as unknown as WorkflowSpec;
  const DOC_SCHEMA = { type: "object", properties: { name: {}, description: {}, budget_usd: {} } };

  it("sets and unsets the workflow's budget", () => {
    const before = documentParams(SPEC);
    const set = paramEdit(null, before, { ...before, budget_usd: 2.5 }, DOC_SCHEMA)!;
    expect(set.ops).toEqual([{ op: "setParam", path: "budget_usd", value: 2.5 }]);
    const budgeted = applyOps(SPEC, set.ops);
    expect(budgeted).toHaveProperty("budget_usd", 2.5);

    const unset = paramEdit(null, documentParams(budgeted), before, DOC_SCHEMA)!;
    expect(applyOps(budgeted, unset.ops)).not.toHaveProperty("budget_usd");
  });

  it("keys an edit by node and paths, so typing in one field is one step", () => {
    const agent = nodeParams(AGENT as unknown as SpecNode, manifest("agent"));
    const first = paramEdit("a", agent, { ...agent, role: "E" }, schemaOf("agent"))!;
    const second = paramEdit("a", agent, { ...agent, role: "Ed" }, schemaOf("agent"))!;
    const other = paramEdit("a", agent, { ...agent, instructions: "X" }, schemaOf("agent"))!;
    expect(first.key).toBe(second.key);
    expect(other.key).not.toBe(first.key);
    expect(paramEdit("a", agent, agent, schemaOf("agent"))).toBeNull();
  });
});
