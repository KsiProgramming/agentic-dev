import type { ElkNode } from "elkjs/lib/elk-api";
import { describe, expect, it } from "vitest";

import docsSpec from "../fixtures/docs-run-spec.json";
import {
  allSpecNodes,
  GAP,
  HEADER,
  LEAF_HEIGHT,
  LEAF_WIDTH,
  PADDING,
  ROUTE_HEADER,
  fromElk,
  layoutSpec,
  routeNodeId,
  specToElk,
  type GraphNode,
  type SpecGraph,
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

const parallel: WorkflowSpec["root"] = {
  type: "parallel",
  id: "review",
  join: "quorum",
  quorum: 2,
  branches: [
    agent("a"),
    { type: "sequence", id: "s", steps: [agent("b"), agent("c")] },
    agent("d"),
  ],
};

const router: WorkflowSpec["root"] = {
  type: "sequence",
  id: "main",
  steps: [
    agent("triage"),
    {
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
    agent("summary"),
  ],
};

/** No two boxes with the same parent overlap. */
function expectNoOverlap(nodes: GraphNode[]) {
  for (const a of nodes) {
    for (const b of nodes) {
      if (a === b || a.parentId !== b.parentId) continue;
      const apart =
        a.position.x + a.width! <= b.position.x ||
        b.position.x + b.width! <= a.position.x ||
        a.position.y + a.height! <= b.position.y ||
        b.position.y + b.height! <= a.position.y;
      expect(apart, `${a.id} overlaps ${b.id}`).toBe(true);
    }
  }
}

/** Every child sits inside its parent, below the parent's title. */
function expectInsideParents(nodes: GraphNode[]) {
  for (const node of nodes) {
    if (!node.parentId) continue;
    const parent = byId(nodes, node.parentId);
    const header = parent.type === "route" ? ROUTE_HEADER : HEADER;
    expect(node.position.y, node.id).toBeGreaterThanOrEqual(header);
    expect(node.position.x, node.id).toBeGreaterThanOrEqual(PADDING);
    expect(node.position.x + node.width!, node.id).toBeLessThanOrEqual(parent.width!);
    expect(node.position.y + node.height!, node.id).toBeLessThanOrEqual(parent.height!);
  }
}

describe("specToElk", () => {
  it("nests ELK nodes as they are drawn, leaves at their size, edges at the root", () => {
    const elk = specToElk(spec_(router));

    expect(elk.layoutOptions?.["elk.hierarchyHandling"]).toBe("INCLUDE_CHILDREN");
    expect(elk.children?.map((c) => c.id)).toEqual(["triage", "report_path", "summary"]);
    const box = elk.children![1]!;
    expect(box.children?.map((c) => c.id)).toEqual([
      routeNodeId("report_path", "clean"),
      routeNodeId("report_path", "fix_first"),
      routeNodeId("report_path", "default"),
    ]);
    expect(box.layoutOptions?.["elk.padding"]).toBe(
      `[top=${HEADER},left=${PADDING},bottom=${PADDING},right=${PADDING}]`,
    );
    const fix = box.children![1]!;
    expect(fix.layoutOptions?.["elk.padding"]).toContain(`top=${ROUTE_HEADER}`);
    expect(fix.children?.map((c) => [c.id, c.width, c.height])).toEqual([
      ["plan", LEAF_WIDTH, LEAF_HEIGHT],
      ["fix_report", LEAF_WIDTH, LEAF_HEIGHT],
    ]);
    expect(elk.edges?.map((e) => e.id)).toEqual([
      "plan->fix_report",
      "triage->report_path",
      "report_path->summary",
    ]);
  });

  it("is the same for the same spec", () => {
    expect(specToElk(spec)).toEqual(specToElk(spec));
  });
});

describe("fromElk", () => {
  it("places each node where ELK put it, relative to its parent, parents first", () => {
    const elk: ElkNode = {
      id: "root",
      children: [
        { id: "first", x: 10, y: 0, width: LEAF_WIDTH, height: LEAF_HEIGHT },
        {
          id: "each",
          x: 0,
          y: 104,
          width: 300,
          height: 200,
          children: [{ id: "worker", x: PADDING, y: HEADER, width: LEAF_WIDTH, height: 64 }],
        },
      ],
    };
    const { nodes, edges } = fromElk(
      spec_({
        type: "sequence",
        id: "main",
        steps: [
          agent("first"),
          { type: "map", id: "each", over: "[1]", max_concurrency: 1, body: agent("worker") },
        ],
      }),
      elk,
    );

    expect(nodes.map((n) => [n.id, n.type, n.parentId])).toEqual([
      ["first", "leaf", undefined],
      ["each", "container", undefined],
      ["worker", "leaf", "each"],
    ]);
    expect(byId(nodes, "each")).toMatchObject({ position: { x: 0, y: 104 }, width: 300 });
    expect(byId(nodes, "worker")).toMatchObject({ position: { x: PADDING, y: HEADER } });
    expect(edges.map((e) => e.id)).toEqual(["first->each"]);
  });

  it("refuses an ELK output that misses a node", () => {
    expect(() => fromElk(spec_(agent("solo")), { id: "root", children: [] })).toThrow(/solo/);
  });
});

describe("layoutSpec on the docs run's spec", () => {
  let graph: SpecGraph;

  it("draws one node per spec node, sequences left out, parents first", async () => {
    graph = await layoutSpec(spec);
    expect(graph.nodes.map((n) => n.id)).toEqual([
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
    const { nodes } = graph;
    expect(byId(nodes, "document").type).toBe("container");
    expect(byId(nodes, "module-writer").parentId).toBe("document");
    expect(byId(nodes, "revise").type).toBe("container");
    expect(byId(nodes, "reviewer").parentId).toBe("revise");
    expect(byId(nodes, "list_modules").parentId).toBeUndefined();
  });

  it("says what each node does", () => {
    const { nodes } = graph;
    expect(byId(nodes, "list_modules").data.detail).toBe("repo.list_modules");
    expect(byId(nodes, "approve").data.detail).toBe("Open the docs PR?");
    expect(byId(nodes, "combine").data.detail).toBe("Concat of document");
  });

  it("links the steps in run order, the reduce labelled with its map", () => {
    expect(graph.edges.map((e) => e.id)).toEqual([
      "list_modules->document",
      "document->combine",
      "combine->revise",
      "revise->approve",
    ]);
    expect(graph.edges.find((e) => e.id === "document->combine")?.label).toBe("reduces");
  });

  it("stacks the steps top to bottom, a body inside its container's padding", () => {
    const { nodes } = graph;
    expectNoOverlap(nodes);
    expectInsideParents(nodes);
    const top = nodes.filter((n) => n.parentId === undefined);
    for (const [a, b] of top.slice(1).map((n, i) => [top[i]!, n] as const)) {
      expect(b.position.y).toBeGreaterThanOrEqual(a.position.y + a.height! + GAP);
    }
  });

  it("gives the same positions for the same spec", async () => {
    expect(await layoutSpec(spec)).toEqual(graph);
  });
});

describe("layoutSpec on other shapes", () => {
  it("draws a loop with a sequence body as a chain inside the loop", async () => {
    const { nodes, edges } = await layoutSpec(
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
    expect(byId(nodes, "check").position.y).toBeGreaterThanOrEqual(
      byId(nodes, "draft").position.y + LEAF_HEIGHT + GAP,
    );
    expectInsideParents(nodes);
  });

  it("links a reduce to a map that is not right before it with a dashed edge", async () => {
    const { edges } = await layoutSpec(
      spec_({
        type: "sequence",
        id: "main",
        steps: [
          { type: "map", id: "each", over: "[1, 2]", max_concurrency: 2, body: agent("worker") },
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

  it("draws a single agent as one node with no edges", async () => {
    const { nodes, edges } = await layoutSpec(spec_(agent("solo")));
    expect(nodes.map((n) => n.id)).toEqual(["solo"]);
    expect(edges).toEqual([]);
  });
});

describe("layoutSpec on a parallel", () => {
  it("draws a box holding its branches side by side, in branch order", async () => {
    const { nodes, edges } = await layoutSpec(spec_(parallel));
    const box = byId(nodes, "review");
    expect(box.type).toBe("container");
    expect(box.data).toMatchObject({ detail: "2 of 3 branches" });
    expect(["a", "b", "c", "d"].map((id) => byId(nodes, id).parentId)).toEqual([
      "review",
      "review",
      "review",
      "review",
    ]);
    const [a, b, d] = ["a", "b", "d"].map((id) => byId(nodes, id));
    expect(a!.position.x).toBeLessThan(b!.position.x);
    expect(b!.position.x).toBeLessThan(d!.position.x);
    expect(byId(nodes, "c").position.y).toBeGreaterThan(b!.position.y);
    expect(edges.map((e) => e.id)).toEqual(["b->c"]);
    expectNoOverlap(nodes);
    expectInsideParents(nodes);
  });

  it("draws a parallel and its vote inside a branch, nested", async () => {
    const { nodes, edges } = await layoutSpec(
      spec_({
        type: "parallel",
        id: "checks",
        join: "all",
        branches: [
          { type: "tool", id: "lint", tool: "scan.lint", args: {} },
          {
            type: "sequence",
            id: "security",
            steps: [
              {
                type: "parallel",
                id: "reviewers",
                join: "all",
                branches: [agent("r1"), agent("r2"), agent("r3")],
              },
              { type: "reduce", id: "vote", from: "reviewers", strategy: "vote" },
            ],
          },
        ],
      }),
    );
    expect(nodes.map((n) => [n.id, n.parentId])).toEqual([
      ["checks", undefined],
      ["lint", "checks"],
      ["reviewers", "checks"],
      ["r1", "reviewers"],
      ["r2", "reviewers"],
      ["r3", "reviewers"],
      ["vote", "checks"],
    ]);
    expect(edges.find((e) => e.id === "reviewers->vote")?.label).toBe("reduces");
    expectNoOverlap(nodes);
    expectInsideParents(nodes);
  });
});

describe("layoutSpec on a router", () => {
  it("draws a box holding one labelled group per route, default last", async () => {
    const { nodes, edges } = await layoutSpec(spec_(router));
    const box = byId(nodes, "report_path");
    expect(box.type).toBe("container");
    expect(box.data).toMatchObject({ kind: "router", detail: "One of 3 routes, by rules" });
    const routes = nodes.filter((n) => n.type === "route");
    expect(routes.map((r) => [r.data.routeId, r.parentId])).toEqual([
      ["clean", "report_path"],
      ["fix_first", "report_path"],
      ["default", "report_path"],
    ]);
    expect(byId(nodes, "plan").parentId).toBe(routeNodeId("report_path", "fix_first"));
    expect(byId(nodes, "standard_report").parentId).toBe(routeNodeId("report_path", "default"));
    const [clean, fix, other] = routes;
    expect(clean!.position.x).toBeLessThan(fix!.position.x);
    expect(fix!.position.x).toBeLessThan(other!.position.x);
    expect(edges.map((e) => e.id)).toEqual([
      "plan->fix_report",
      "triage->report_path",
      "report_path->summary",
    ]);
    expectNoOverlap(nodes);
    expectInsideParents(nodes);
  });

  it("walks the routes and the default in allSpecNodes", () => {
    expect(allSpecNodes(spec_(router)).map((n) => n.id)).toEqual([
      "main",
      "triage",
      "report_path",
      "clean_report",
      "fix",
      "plan",
      "fix_report",
      "standard_report",
      "summary",
    ]);
  });

  it("says a classifier chooses", async () => {
    const { nodes } = await layoutSpec(
      spec_({
        type: "router",
        id: "kind",
        classifier: { instructions: "Choose." },
        routes: [{ id: "bug", then: agent("fix") }],
      }),
    );
    expect(byId(nodes, "kind").data).toMatchObject({ detail: "One of 1 route, by a classifier" });
  });
});
