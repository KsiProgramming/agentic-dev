import type { Edge, Node } from "@xyflow/react";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";

import type { components } from "@/api/schema";

/**
 * The run's workflow as a graph to draw: one node per spec node, top to bottom in run order.
 * Sequences are not drawn, only their steps; a loop or a map is a box holding its body, a
 * parallel a box holding its branches side by side, and a router (4.6) a box holding one group
 * per route, labelled with the route's id. ELK lays it out (`layoutSpec`): `specToElk` builds
 * its input and `fromElk` places the drawn nodes from its output, both pure, so the same spec
 * always gives the same graph.
 */

export type WorkflowSpec = components["schemas"]["WorkflowSpec"];
export type SpecNode = WorkflowSpec["root"];
export type NodeKind = SpecNode["type"];
type RouterSpec = Extract<SpecNode, { type: "router" }>;

export interface GraphNodeData extends Record<string, unknown> {
  kind: NodeKind;
  /** The spec node id. */
  nodeId: string;
  /** One line on what the node does: an agent's role, a tool's name, a gate's title. */
  detail: string;
}

/** One route of a router: not a spec node, a labelled group of the route's steps. */
export interface RouteData extends Record<string, unknown> {
  routerId: string;
  /** The route's id, `default` for the router's default. */
  routeId: string;
}

export type LeafNode = Node<GraphNodeData, "leaf">;
export type ContainerNode = Node<GraphNodeData, "container">;
export type RouteNode = Node<RouteData, "route">;
export type GraphNode = LeafNode | ContainerNode | RouteNode;

export interface SpecGraph {
  /** Parents come before their children, as React Flow requires. */
  nodes: GraphNode[];
  edges: Edge[];
}

export const LEAF_WIDTH = 240;
export const LEAF_HEIGHT = 64;
/** Between two steps of a sequence, and between two branches of a parallel. */
export const GAP = 40;
/** Around a container's body. */
export const PADDING = 16;
/** A container's title above its body. */
export const HEADER = 56;
/** A route's label above its steps. */
export const ROUTE_HEADER = 32;

export const DEFAULT_ROUTE = "default";

/** The id of the group drawn for route `routeId` of router `routerId`. Spec node ids have no
 * `:`, so it never clashes with one. */
export function routeNodeId(routerId: string, routeId: string): string {
  return `${routerId}:route:${routeId}`;
}

const REDUCE_LABEL: Record<Extract<SpecNode, { type: "reduce" }>["strategy"], string> = {
  agent: "Agent",
  concat: "Concat",
  dedupe: "Dedupe",
  vote: "Vote",
};

function detail(node: SpecNode): string {
  switch (node.type) {
    case "agent":
      return node.role;
    case "tool":
      return node.tool;
    case "gate":
      return node.title;
    case "reduce":
      return `${REDUCE_LABEL[node.strategy]} of ${node.from}`;
    case "loop":
      return `Up to ${node.max_iterations} iterations`;
    case "map":
      return `Each item, ${node.max_concurrency} at a time`;
    case "parallel": {
      const n = node.branches.length;
      if (node.join === "all") return `All ${n} branches`;
      if (node.join === "any") return `Any of ${n} branches`;
      return `${node.quorum ?? n} of ${n} branches`;
    }
    case "router": {
      const n = routesOf(node).length;
      const by = node.classifier ? "a classifier" : "rules";
      return `One of ${n} ${n === 1 ? "route" : "routes"}, by ${by}`;
    }
    case "sequence":
      return "";
  }
}

/** A router's routes as `[route id, what runs on it]`, `default` last. */
export function routesOf(router: RouterSpec): [string, SpecNode][] {
  const routes: [string, SpecNode][] = router.routes.map((r) => [r.id, r.then]);
  if (router.default) routes.push([DEFAULT_ROUTE, router.default]);
  return routes;
}

function edge(source: string, target: string): Edge {
  return { id: `${source}->${target}`, source, target, type: "smoothstep" };
}

/** How every level is laid out: ELK reads these per box, they are not inherited. */
const LAYERED: Record<string, string> = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.spacing.nodeNode": String(GAP),
  "elk.layered.spacing.nodeNodeBetweenLayers": String(GAP),
  "elk.layered.spacing.edgeNodeBetweenLayers": String(GAP / 2),
  // Branches and routes keep the spec's order, left to right.
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
};

const ROOT_OPTIONS: Record<string, string> = {
  ...LAYERED,
  // Edges between nodes of different boxes (a reduce of a map) are routed through the boxes.
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
};

const boxPadding = (top: number) =>
  `[top=${top},left=${PADDING},bottom=${PADDING},right=${PADDING}]`;

/** The drawn node of each spec node and route, with its parent, in the order React Flow needs
 * them (parents first), and the run-order edges between them. */
interface Shape {
  nodes: { id: string; parentId: string | undefined; data: GraphNodeData | RouteData }[];
  edges: Edge[];
}

/** Adds `node` (in `parentId`) to `shape` and returns the ids an edge enters it at and leaves it
 * from. A sequence is its steps, chained. */
function walk(node: SpecNode, parentId: string | undefined, shape: Shape): [string, string] {
  if (node.type === "sequence") {
    const ends = node.steps.map((step) => walk(step, parentId, shape));
    ends.forEach(([entry], i) => {
      const previous = ends[i - 1];
      if (previous) shape.edges.push(edge(previous[1], entry));
    });
    return [ends[0]![0], ends.at(-1)![1]];
  }
  const data: GraphNodeData = { kind: node.type, nodeId: node.id, detail: detail(node) };
  shape.nodes.push({ id: node.id, parentId, data });
  switch (node.type) {
    case "loop":
    case "map":
      walk(node.body, node.id, shape);
      break;
    case "parallel":
      for (const branch of node.branches) walk(branch, node.id, shape);
      break;
    case "router":
      for (const [routeId, route] of routesOf(node)) {
        const id = routeNodeId(node.id, routeId);
        shape.nodes.push({ id, parentId: node.id, data: { routerId: node.id, routeId } });
        walk(route, id, shape);
      }
      break;
    default:
      break;
  }
  return [node.id, node.id];
}

function shapeOf(spec: WorkflowSpec): Shape {
  const shape: Shape = { nodes: [], edges: [] };
  walk(spec.root, undefined, shape);
  for (const node of specNodes(spec.root)) {
    if (node.type !== "reduce") continue;
    const id = `${node.from}->${node.id}`;
    const existing = shape.edges.find((e) => e.id === id);
    if (existing) {
      existing.label = "reduces";
    } else {
      // Not the step right before it: a dashed link, apart from the run order.
      shape.edges.push({
        id,
        source: node.from,
        target: node.id,
        type: "smoothstep",
        label: "reduces",
        style: { strokeDasharray: "4 4" },
      });
    }
  }
  return shape;
}

const isRoute = (data: GraphNodeData | RouteData): data is RouteData => "routeId" in data;

/** ELK's input for `spec`: one ELK node per drawn node, nested as they are drawn, leaves at
 * their fixed size, every edge at the root (`INCLUDE_CHILDREN` routes it). */
export function specToElk(spec: WorkflowSpec): ElkNode {
  const shape = shapeOf(spec);
  const elk = new Map<string, ElkNode>();
  const root: ElkNode = { id: "root", layoutOptions: ROOT_OPTIONS, children: [] };
  for (const { id, parentId, data } of shape.nodes) {
    const box = isRoute(data) || ["loop", "map", "parallel", "router"].includes(data.kind);
    const node: ElkNode = box
      ? {
          id,
          children: [],
          layoutOptions: {
            ...LAYERED,
            "elk.padding": boxPadding(isRoute(data) ? ROUTE_HEADER : HEADER),
            // An empty box still has room for its title.
            "elk.nodeSize.constraints": "MINIMUM_SIZE",
            "elk.nodeSize.minimum": `(${LEAF_WIDTH + 2 * PADDING}, ${HEADER + PADDING})`,
          },
        }
      : { id, width: LEAF_WIDTH, height: LEAF_HEIGHT };
    elk.set(id, node);
    const parent = parentId ? elk.get(parentId) : root;
    parent!.children!.push(node);
  }
  root.edges = shape.edges.map((e): ElkExtendedEdge => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));
  return root;
}

/** The drawn graph of `spec`, placed where ELK put each node (`laidOut`, ELK's output for
 * `specToElk(spec)`; a position is relative to the node's parent, as in React Flow). */
export function fromElk(spec: WorkflowSpec, laidOut: ElkNode): SpecGraph {
  const placed = new Map<string, ElkNode>();
  const visit = (node: ElkNode) => {
    placed.set(node.id, node);
    for (const child of node.children ?? []) visit(child);
  };
  visit(laidOut);
  const shape = shapeOf(spec);
  const nodes = shape.nodes.map(({ id, parentId, data }): GraphNode => {
    const at = placed.get(id);
    if (!at) throw new Error(`ELK did not place ${id}`);
    const common = {
      id,
      position: { x: at.x ?? 0, y: at.y ?? 0 },
      width: at.width ?? LEAF_WIDTH,
      height: at.height ?? LEAF_HEIGHT,
      ...(parentId ? { parentId, extent: "parent" as const } : {}),
    };
    if (isRoute(data)) return { ...common, type: "route", data };
    const box = ["loop", "map", "parallel", "router"].includes(data.kind);
    return box ? { ...common, type: "container", data } : { ...common, type: "leaf", data };
  });
  return { nodes, edges: shape.edges };
}

/** Lays `spec` out with ELK, loaded on first use so it stays out of the page's bundle. */
export async function layoutSpec(spec: WorkflowSpec): Promise<SpecGraph> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  const laidOut = await new ELK().layout(specToElk(spec));
  return fromElk(spec, laidOut);
}

function* specNodes(node: SpecNode): Generator<SpecNode> {
  yield node;
  if (node.type === "sequence") for (const step of node.steps) yield* specNodes(step);
  if (node.type === "loop" || node.type === "map") yield* specNodes(node.body);
  if (node.type === "parallel") for (const branch of node.branches) yield* specNodes(branch);
  if (node.type === "router") for (const [, route] of routesOf(node)) yield* specNodes(route);
}

/** Every node of the spec, depth first in run order, sequences included. */
export function allSpecNodes(spec: WorkflowSpec): SpecNode[] {
  return [...specNodes(spec.root)];
}
