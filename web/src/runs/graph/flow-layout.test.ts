import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { withCalls } from "../calls";
import { orchestratorRun } from "../fixtures/orchestrator-run";
import { subflowRun } from "../fixtures/subflow-run";
import { flowLayout, type FlowLayout } from "./flow-layout";
import type { SpecNode, WorkflowSpec } from "./spec-graph";

const VALID = resolve(__dirname, "../../../../packages/engine/tests/fixtures/specs/valid");
const read = (path: string) => JSON.parse(readFileSync(path, "utf8")) as WorkflowSpec;

/** Every workflow the repo keeps as a fixture: the engine's valid specs and the recorded runs. */
const SPECS: [string, WorkflowSpec][] = [
  ...readdirSync(VALID)
    .filter((f) => f.endsWith(".json"))
    .map((f): [string, WorkflowSpec] => [f, read(resolve(VALID, f))]),
  ["orchestrator-run", orchestratorRun.spec],
  ["subflow-run (with calls)", withCalls(subflowRun.spec, subflowRun.calls)],
];

const TEAM = read(resolve(VALID, "team-review-pr.json"));

function cell(layout: FlowLayout, id: string): [number, number] {
  const found = layout.cards.find((c) => c.node.id === id);
  if (!found) throw new Error(`no card ${id}`);
  return [found.col, found.row];
}

/** The node ids of a spec that are drawn as cards: every node but a sequence. */
function drawn(node: SpecNode, out: string[] = []): string[] {
  if (node.type !== "sequence") out.push(node.id);
  if (node.type === "sequence") node.steps.forEach((s) => drawn(s, out));
  if (node.type === "loop" || node.type === "map" || node.type === "orchestrator") {
    drawn(node.body, out);
  }
  if (node.type === "parallel") node.branches.forEach((b) => drawn(b, out));
  if (node.type === "router") {
    node.routes.forEach((r) => drawn(r.then, out));
    if (node.default) drawn(node.default, out);
  }
  return out;
}

describe.each(SPECS)("the flow of %s", (_, spec) => {
  const layout = flowLayout(spec);

  it("puts every card in a cell of its own", () => {
    const cells = layout.cards.map((c) => `${c.col},${c.row}`);
    expect(new Set(cells).size).toBe(cells.length);
    for (const c of layout.cards) {
      expect(c.col).toBeLessThan(layout.cols);
      expect(c.row).toBeLessThan(layout.rows);
    }
  });

  it("joins only cards it draws", () => {
    const ids = new Set(layout.cards.map((c) => c.node.id));
    for (const edge of layout.edges) {
      expect(ids.has(edge.from), edge.from).toBe(true);
      expect(ids.has(edge.to), edge.to).toBe(true);
    }
  });

  it("reads left to right: every forward edge goes right", () => {
    for (const edge of layout.edges.filter((e) => e.kind !== "back")) {
      expect(cell(layout, edge.to)[0]).toBeGreaterThan(cell(layout, edge.from)[0]);
    }
  });

  it("draws loops back, and only loops", () => {
    for (const edge of layout.edges.filter((e) => e.kind === "back")) {
      const loop = layout.cards.find((c) => c.node.id === edge.to)!;
      expect(loop.node.kind).toBe("loop");
      expect(cell(layout, edge.from)[0]).toBeGreaterThan(loop.col);
    }
  });

  it("is the same for the same spec", () => {
    expect(flowLayout(spec)).toEqual(layout);
  });
});

it("draws every node but sequences, a builder's subflow as one card", () => {
  for (const [, spec] of SPECS.slice(0, -1)) {
    expect(flowLayout(spec).cards.map((c) => c.node.id)).toEqual(drawn(spec.root));
  }
});

describe("a team workflow (team-review-pr)", () => {
  const layout = flowLayout(TEAM);

  it("forks the orchestrator into its worker's lane, then goes on to the synthesizer", () => {
    expect(cell(layout, "implement")).toEqual([0, 0]);
    expect(cell(layout, "engineer")).toEqual([1, 0]);
    expect(cell(layout, "task_review")).toEqual([2, 0]);
    expect(cell(layout, "synthesizer")).toEqual([3, 0]);
    expect(cell(layout, "reviewer")).toEqual([4, 0]);
    expect(layout.lanes).toContainEqual({
      id: "implement",
      col: 1,
      row: 0,
      cols: 2,
      rows: 1,
      label: "Each task",
    });
    expect(layout.edges).toContainEqual({
      from: "task_review",
      to: "synthesizer",
      kind: "flow",
      label: null,
      route: null,
    });
  });

  it("draws the router's routes as labelled lanes, `default` below", () => {
    expect(cell(layout, "decision")).toEqual([5, 0]);
    expect(cell(layout, "approve_pr")).toEqual([6, 0]);
    expect(cell(layout, "open_pr")).toEqual([7, 0]);
    expect(cell(layout, "report_changes")).toEqual([6, 1]);
    const forks = layout.edges.filter((e) => e.from === "decision");
    expect(forks.map((e) => [e.to, e.label, e.route])).toEqual([
      ["approve_pr", "ok", "decision:route:ok"],
      ["report_changes", "default", "decision:route:default"],
    ]);
    expect([layout.cols, layout.rows]).toEqual([8, 2]);
  });
});

it("draws a loop's back edge, labelled with its condition", () => {
  const layout = flowLayout({
    spec_version: "0",
    id: "looped",
    name: "Looped",
    root: {
      type: "sequence",
      id: "main",
      steps: [
        {
          type: "loop",
          id: "again",
          until: "iteration >= 2",
          max_iterations: 3,
          body: {
            type: "sequence",
            id: "body",
            steps: [
              { type: "agent", id: "write", role: "W", instructions: "Go." },
              { type: "agent", id: "check", role: "C", instructions: "Go." },
            ],
          },
        },
        { type: "agent", id: "after", role: "A", instructions: "Go." },
      ],
    },
  } as unknown as WorkflowSpec);
  expect(layout.edges.filter((e) => e.kind === "back")).toEqual([
    { from: "check", to: "again", kind: "back", label: null, route: null },
  ]);
  expect(layout.lanes).toContainEqual({
    id: "again",
    col: 1,
    row: 0,
    cols: 2,
    rows: 1,
    label: "Repeats until iteration >= 2",
  });
  expect(layout.edges).toContainEqual({
    from: "check",
    to: "after",
    kind: "flow",
    label: null,
    route: null,
  });
});

it("frames the workflow a subflow called in a run", () => {
  const layout = flowLayout(withCalls(subflowRun.spec, subflowRun.calls));
  expect(layout.cards.map((c) => c.node.id)).toEqual([
    "agent_1",
    "review",
    "review-agent_1",
    "verdict",
    "summary",
  ]);
  expect(layout.lanes).toEqual([
    { id: "review", col: 2, row: 0, cols: 2, rows: 1, label: "Calls checks · version 2" },
  ]);
});

describe("wrapping into rows", () => {
  it.each(SPECS)("keeps %s in cells of its own at every width", (_, spec) => {
    for (const maxCols of [1, 2, 3, 4, 6]) {
      const layout = flowLayout(spec, maxCols);
      const cells = layout.cards.map((c) => `${c.col},${c.row}`);
      expect(new Set(cells).size).toBe(cells.length);
      expect(layout.cards.map((c) => c.node.id)).toEqual(
        flowLayout(spec).cards.map((c) => c.node.id),
      );
      for (const edge of layout.edges.filter((e) => e.kind === "flow" || e.kind === "fork")) {
        expect(cell(layout, edge.to)[0]).toBeGreaterThan(cell(layout, edge.from)[0]);
      }
      // A wrap goes down to a new row and back left, to its sequence's first column.
      for (const edge of layout.edges.filter((e) => e.kind === "wrap")) {
        expect(cell(layout, edge.to)[1]).toBeGreaterThan(cell(layout, edge.from)[1]);
        expect(cell(layout, edge.to)[0]).toBeLessThanOrEqual(cell(layout, edge.from)[0]);
      }
    }
  });

  it("breaks team-review-pr after the synthesizer when 4 columns fit, never inside a lane", () => {
    const layout = flowLayout(TEAM, 4);
    expect(cell(layout, "implement")).toEqual([0, 0]);
    expect(cell(layout, "task_review")).toEqual([2, 0]);
    expect(cell(layout, "synthesizer")).toEqual([3, 0]);
    expect(cell(layout, "reviewer")).toEqual([0, 1]);
    expect(cell(layout, "decision")).toEqual([1, 1]);
    expect(cell(layout, "open_pr")).toEqual([3, 1]);
    expect(cell(layout, "report_changes")).toEqual([2, 2]);
    expect(layout.edges.filter((e) => e.kind === "wrap")).toEqual([
      { from: "synthesizer", to: "reviewer", kind: "wrap", label: null, route: null },
    ]);
    expect([layout.cols, layout.rows]).toEqual([4, 3]);
  });

  it("fits a narrow pane by wrapping inside lanes too", () => {
    const layout = flowLayout(TEAM, 2);
    expect(cell(layout, "implement")).toEqual([0, 0]);
    expect(cell(layout, "engineer")).toEqual([1, 0]);
    expect(cell(layout, "task_review")).toEqual([1, 1]);
    expect(cell(layout, "synthesizer")).toEqual([0, 2]);
    expect(cell(layout, "reviewer")).toEqual([1, 2]);
    expect(cell(layout, "decision")).toEqual([0, 3]);
    expect(layout.cols).toBe(2);
  });
});

it("wraps a loop's long body inside its lane, under the lane's first column", () => {
  const VALID = resolve(__dirname, "../../../../packages/engine/tests/fixtures/specs/valid");
  const spec = read(resolve(VALID, "plan-execute-reflect.json"));
  const layout = flowLayout(spec, 3);
  expect(cell(layout, "refine")).toEqual([0, 1]);
  expect(cell(layout, "decomposer")).toEqual([1, 1]);
  expect(cell(layout, "scheduler")).toEqual([2, 1]);
  expect(cell(layout, "executor")).toEqual([1, 2]);
  expect(cell(layout, "monitor")).toEqual([2, 2]);
  expect(cell(layout, "output")).toEqual([0, 3]);
  expect(layout.lanes).toEqual([
    {
      id: "refine",
      col: 1,
      row: 1,
      cols: 2,
      rows: 2,
      label: "Repeats until results.monitor.data.ok == true",
    },
  ]);
  expect(layout.edges.filter((e) => e.kind === "back")).toEqual([
    { from: "monitor", to: "refine", kind: "back", label: null, route: null },
  ]);
  expect(layout.cols).toBe(3);
});
