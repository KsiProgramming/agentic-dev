import { describe, expect, it } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";

import { diffSpecs, summarizeDiff } from "./diff";

const agent = (id: string, extra: Record<string, unknown> = {}) => ({
  type: "agent" as const,
  id,
  role: id,
  instructions: `Do ${id}.`,
  ...extra,
});

const spec = (steps: unknown[], extra: Record<string, unknown> = {}) =>
  ({
    spec_version: "0",
    id: "flow",
    name: "Flow",
    root: { type: "sequence", id: "main", steps },
    ...extra,
  }) as unknown as WorkflowSpec;

const loop = (id: string, body: unknown) => ({
  type: "loop",
  id,
  body,
  until: "true",
  max_iterations: 2,
});

const BASE = spec([agent("a"), loop("l", agent("b")), agent("c")]);

describe("version diff", () => {
  it("finds nothing between a spec and itself", () => {
    const diff = diffSpecs(BASE, structuredClone(BASE));
    expect(diff.nodes.size).toBe(0);
    expect(diff.removed).toEqual([]);
    expect(diff.document).toEqual([]);
    expect(summarizeDiff(diff)).toBe("No changes");
  });

  it("marks added nodes, and does not count their neighbours as moved", () => {
    const after = spec([agent("a"), agent("new"), loop("l", agent("b")), agent("c")]);
    const diff = diffSpecs(BASE, after);
    expect([...diff.nodes]).toEqual([["new", { kind: "added" }]]);
    expect(summarizeDiff(diff)).toBe("1 added");
  });

  it("lists removed nodes with everything under them, in run order", () => {
    const after = spec([agent("a"), agent("c")]);
    const diff = diffSpecs(BASE, after);
    expect(diff.removed).toEqual([
      { id: "l", type: "loop" },
      { id: "b", type: "agent" },
    ]);
    expect(diff.nodes.size).toBe(0);
    expect(summarizeDiff(diff)).toBe("2 removed");
  });

  it("marks a step moved within its sequence, and one moved into another container", () => {
    const swapped = diffSpecs(BASE, spec([agent("c"), agent("a"), loop("l", agent("b"))]));
    expect(swapped.nodes.get("c")).toEqual({ kind: "moved" });
    expect(swapped.nodes.get("b")).toBeUndefined();

    const into = diffSpecs(
      BASE,
      spec([agent("a"), loop("l", { type: "sequence", id: "s", steps: [agent("b"), agent("c")] })]),
    );
    expect(into.nodes.get("c")).toEqual({ kind: "moved" });
    expect(into.nodes.get("b")).toEqual({ kind: "moved" });
    expect(into.nodes.get("s")).toEqual({ kind: "added" });
  });

  it("lists each changed parameter, nested paths included, and an unset one", () => {
    const after = spec([
      agent("a", { instructions: "Plan it.", tools: ["repo.read"] }),
      loop("l", agent("b")),
      agent("c"),
    ]);
    const diff = diffSpecs(
      spec([agent("a", { budget_usd: 2 }), loop("l", agent("b")), agent("c")]),
      after,
    );
    expect(diff.nodes.get("a")).toEqual({
      kind: "changed",
      moved: false,
      changes: [
        { path: "instructions", before: "Do a.", after: "Plan it." },
        { path: "budget_usd", before: 2, after: undefined },
        { path: "tools", before: undefined, after: ["repo.read"] },
      ],
    });
  });

  it("compares a router's routes without what runs on them", () => {
    const router = (when: string, then: unknown) => ({
      type: "router",
      id: "r",
      classifier: { instructions: "Pick." },
      routes: [{ id: "big", when, then }],
    });
    const diff = diffSpecs(
      spec([router("size > 3", agent("x"))]),
      spec([router("size > 5", agent("y"))]),
    );
    expect(diff.nodes.get("r")).toEqual({
      kind: "changed",
      moved: false,
      changes: [{ path: "routes[0].when", before: "size > 3", after: "size > 5" }],
    });
    expect(diff.nodes.get("y")).toEqual({ kind: "added" });
    expect(diff.removed).toEqual([{ id: "x", type: "agent" }]);
  });

  it("lists the workflow's own fields that changed, null and unset being the same", () => {
    const diff = diffSpecs(
      spec([agent("a")], { description: null }),
      spec([agent("a")], { name: "Renamed", budget_usd: 5 }),
    );
    expect(diff.document).toEqual([
      { path: "name", before: "Flow", after: "Renamed" },
      { path: "budget_usd", before: undefined, after: 5 },
    ]);
    expect(summarizeDiff(diff)).toBe("2 workflow fields");
  });

  it("marks a node both moved and changed as changed", () => {
    const diff = diffSpecs(
      BASE,
      spec([agent("c", { role: "Checker" }), agent("a"), loop("l", agent("b"))]),
    );
    expect(diff.nodes.get("c")).toEqual({
      kind: "changed",
      moved: true,
      changes: [{ path: "role", before: "c", after: "Checker" }],
    });
    expect(summarizeDiff(diff)).toBe("1 changed");
  });
});
