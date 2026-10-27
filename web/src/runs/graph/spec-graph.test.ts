import { describe, expect, it } from "vitest";

import docsSpec from "../fixtures/docs-run-spec.json";
import {
  GAP,
  HEADER,
  LEAF_HEIGHT,
  LEAF_WIDTH,
  PADDING,
  specToGraph,
  type GraphNode,
  type WorkflowSpec,
} from "./spec-graph";

const spec = docsSpec as WorkflowSpec;

function byId(nodes: GraphNode[], id: string): GraphNode {
  const node = nodes.find((n) => n.id === id);
  if (!node) throw new Error(`no node ${id}`);
  return node;
}

function spec_(root: WorkflowSpec["root"]): WorkflowSpec {
  return { spec_version: "0", id: "w", name: "W", root };
}

const agent = (id: string): WorkflowSpec["root"] => ({
  type: "agent",
  id,
  role: `role of ${id}`,
  instructions: "go",
  tools: [],
});

describe("specToGraph on the docs run's spec", () => {
  const { nodes, edges } = specToGraph(spec);

  it("draws one node per spec node, sequences left out, parents first", () => {
    expect(nodes.map((n) => n.id)).toEqual([
      "list_modules",
      "document",
      "module-writer",
      "combine",
      "revise",
      "reviewer",
      "approve",
    ]);
  });

  it("draws the map and the loop as containers holding their body", () => {
    expect(byId(nodes, "document").type).toBe("container");
    expect(byId(nodes, "module-writer").parentId).toBe("document");
    expect(byId(nodes, "revise").type).toBe("container");
    expect(byId(nodes, "reviewer").parentId).toBe("revise");
    expect(byId(nodes, "list_modules").parentId).toBeUndefined();
  });

  it("says what each node does", () => {
    expect(byId(nodes, "list_modules").data.detail).toBe("repo.list_modules");
    expect(byId(nodes, "module-writer").data.detail).toBe(
      "Technical writer documenting one module",
    );
    expect(byId(nodes, "approve").data.detail).toBe("Open the docs PR?");
    expect(byId(nodes, "combine").data.detail).toBe("Concat of document");
  });

  it("links the steps in run order, the reduce labelled with its map", () => {
    expect(edges.map((e) => e.id)).toEqual([
      "list_modules->document",
      "document->combine",
      "combine->revise",
      "revise->approve",
    ]);
    expect(edges.find((e) => e.id === "document->combine")?.label).toBe("reduces");
  });

  it("stacks the steps top to bottom, a body inside its container's padding", () => {
    const writer = byId(nodes, "module-writer");
    expect(writer.position).toEqual({ x: PADDING, y: HEADER });
    const document = byId(nodes, "document");
    expect(document.width).toBe(LEAF_WIDTH + 2 * PADDING);
    expect(document.height).toBe(HEADER + LEAF_HEIGHT + PADDING);
    expect(document.position.y).toBe(LEAF_HEIGHT + GAP);
    expect(byId(nodes, "combine").position.y).toBe(document.position.y + document.height! + GAP);
  });

  it("gives the same positions for the same spec", () => {
    expect(specToGraph(spec)).toEqual(specToGraph(spec));
  });
});

describe("specToGraph on other shapes", () => {
  it("draws a loop with a sequence body as a chain inside the loop", () => {
    const { nodes, edges } = specToGraph(
      spec_({
        type: "loop",
        id: "review",
        until: "true",
        max_iterations: 3,
        body: { type: "sequence", id: "body", steps: [agent("draft"), agent("check")] },
      }),
    );
    expect(nodes.map((n) => [n.id, n.parentId])).toEqual([
      ["review", undefined],
      ["draft", "review"],
      ["check", "review"],
    ]);
    expect(edges.map((e) => e.id)).toEqual(["draft->check"]);
    expect(byId(nodes, "check").position.y).toBe(HEADER + LEAF_HEIGHT + GAP);
  });

  it("links a reduce to a map that is not right before it with a dashed edge", () => {
    const { edges } = specToGraph(
      spec_({
        type: "sequence",
        id: "main",
        steps: [
          {
            type: "map",
            id: "each",
            over: "[1, 2]",
            max_concurrency: 2,
            body: agent("worker"),
          },
          { type: "tool", id: "note", tool: "repo.list_files", args: {} },
          { type: "reduce", id: "all", from: "each", strategy: "concat" },
          { type: "gate", id: "ok", title: "OK?" },
        ],
      }),
    );
    expect(edges.map((e) => e.id)).toEqual(["each->note", "note->all", "all->ok", "each->all"]);
    const reference = edges.at(-1)!;
    expect(reference.label).toBe("reduces");
    expect(reference.style).toEqual({ strokeDasharray: "4 4" });
  });

  it("centres narrower steps under wider ones and never overlaps siblings", () => {
    const { nodes } = specToGraph(
      spec_({
        type: "sequence",
        id: "main",
        steps: [
          agent("first"),
          { type: "map", id: "each", over: "[1]", max_concurrency: 1, body: agent("worker") },
          agent("last"),
        ],
      }),
    );
    expect(byId(nodes, "first").position.x).toBe(PADDING);
    expect(byId(nodes, "each").position.x).toBe(0);
    const top = nodes.filter((n) => n.parentId === undefined);
    for (const [a, b] of top.slice(1).map((n, i) => [top[i]!, n] as const)) {
      expect(b.position.y).toBeGreaterThanOrEqual(a.position.y + a.height! + GAP);
    }
  });

  it("draws a single agent as one node with no edges", () => {
    const { nodes, edges } = specToGraph(spec_(agent("solo")));
    expect(nodes.map((n) => n.id)).toEqual(["solo"]);
    expect(edges).toEqual([]);
  });
});

describe("specToGraph on a parallel", () => {
  const { nodes, edges } = specToGraph(
    spec_({
      type: "parallel",
      id: "review",
      join: "quorum",
      quorum: 2,
      branches: [
        agent("a"),
        { type: "sequence", id: "s", steps: [agent("b"), agent("c")] },
        agent("d"),
      ],
    }),
  );

  it("draws a box holding its branches side by side, top aligned", () => {
    const box = byId(nodes, "review");
    expect(box.type).toBe("container");
    expect(box.data.detail).toBe("2 of 3 branches");
    expect(["a", "b", "c", "d"].map((id) => byId(nodes, id).parentId)).toEqual([
      "review",
      "review",
      "review",
      "review",
    ]);
    expect(byId(nodes, "a").position).toEqual({ x: PADDING, y: HEADER });
    expect(byId(nodes, "b").position).toEqual({ x: PADDING + LEAF_WIDTH + GAP, y: HEADER });
    expect(byId(nodes, "c").position).toEqual({
      x: PADDING + LEAF_WIDTH + GAP,
      y: HEADER + LEAF_HEIGHT + GAP,
    });
    expect(byId(nodes, "d").position).toEqual({ x: PADDING + 2 * (LEAF_WIDTH + GAP), y: HEADER });
    expect(box.width).toBe(3 * LEAF_WIDTH + 2 * GAP + 2 * PADDING);
    expect(box.height).toBe(HEADER + 2 * LEAF_HEIGHT + GAP + PADDING);
  });

  it("links only the steps inside a branch", () => {
    expect(edges.map((e) => e.id)).toEqual(["b->c"]);
  });
});
