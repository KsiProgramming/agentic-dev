import type { Edge, Node } from "@xyflow/react";

import type { components } from "@/api/schema";

/**
 * The run's workflow as a graph to draw: one node per spec node, top to bottom in run order.
 * Sequences are not drawn, only their steps; a loop or a map is a box holding its body. The spec
 * is a tree, so the layout is placed by hand, and the same spec always gives the same positions.
 */

export type WorkflowSpec = components["schemas"]["WorkflowSpec"];
export type SpecNode = WorkflowSpec["root"];
export type NodeKind = SpecNode["type"];

export interface GraphNodeData extends Record<string, unknown> {
  kind: NodeKind;
  /** The spec node id. */
  nodeId: string;
  /** One line on what the node does: an agent's role, a tool's name, a gate's title. */
  detail: string;
}

export type LeafNode = Node<GraphNodeData, "leaf">;
export type ContainerNode = Node<GraphNodeData, "container">;
export type GraphNode = LeafNode | ContainerNode;

export interface SpecGraph {
  /** Parents come before their children, as React Flow requires. */
  nodes: GraphNode[];
  edges: Edge[];
}

export const LEAF_WIDTH = 240;
export const LEAF_HEIGHT = 64;
/** Between two steps of a sequence. */
export const GAP = 40;
/** Around a container's body. */
export const PADDING = 16;
/** A container's title above its body. */
export const HEADER = 56;

/** A laid-out piece of the spec, its own nodes placed from (0, 0). */
interface Block {
  width: number;
  height: number;
  nodes: GraphNode[];
  edges: Edge[];
  /** Where an edge into the block ends, and where one out of it starts. */
  entry: string;
  exit: string;
}

function detail(node: SpecNode): string {
  switch (node.type) {
    case "agent":
      return node.role;
    case "tool":
      return node.tool;
    case "gate":
      return node.title;
    case "reduce":
      return `${node.strategy === "agent" ? "Agent" : "Concat"} of ${node.from}`;
    case "loop":
      return `Up to ${node.max_iterations} iterations`;
    case "map":
      return `Each item, ${node.max_concurrency} at a time`;
    case "sequence":
      return "";
  }
}

function edge(source: string, target: string): Edge {
  return { id: `${source}->${target}`, source, target, type: "smoothstep" };
}

/** Moves the nodes `parentId` holds directly; deeper ones are placed in their own parent. */
function shift(nodes: GraphNode[], parentId: string | undefined, dx: number, dy: number) {
  for (const node of nodes) {
    if (node.parentId === parentId) {
      node.position = { x: node.position.x + dx, y: node.position.y + dy };
    }
  }
}

function layout(node: SpecNode, parentId: string | undefined): Block {
  const data: GraphNodeData = { kind: node.type, nodeId: node.id, detail: detail(node) };
  switch (node.type) {
    case "sequence": {
      const blocks = node.steps.map((step) => layout(step, parentId));
      const width = Math.max(...blocks.map((b) => b.width));
      const nodes: GraphNode[] = [];
      const edges: Edge[] = [];
      let y = 0;
      blocks.forEach((block, i) => {
        // Steps are centred under each other.
        shift(block.nodes, parentId, (width - block.width) / 2, y);
        nodes.push(...block.nodes);
        edges.push(...block.edges);
        const previous = blocks[i - 1];
        if (previous) edges.push(edge(previous.exit, block.entry));
        y += block.height + GAP;
      });
      return {
        width,
        height: y - GAP,
        nodes,
        edges,
        entry: blocks[0]!.entry,
        exit: blocks.at(-1)!.exit,
      };
    }
    case "loop":
    case "map": {
      const body = layout(node.body, node.id);
      shift(body.nodes, node.id, PADDING, HEADER);
      const width = body.width + 2 * PADDING;
      const height = HEADER + body.height + PADDING;
      const container: ContainerNode = {
        id: node.id,
        type: "container",
        data,
        position: { x: 0, y: 0 },
        width,
        height,
        ...(parentId ? { parentId, extent: "parent" as const } : {}),
      };
      return {
        width,
        height,
        nodes: [container, ...body.nodes],
        edges: body.edges,
        entry: node.id,
        exit: node.id,
      };
    }
    default: {
      const leaf: LeafNode = {
        id: node.id,
        type: "leaf",
        data,
        position: { x: 0, y: 0 },
        width: LEAF_WIDTH,
        height: LEAF_HEIGHT,
        ...(parentId ? { parentId, extent: "parent" as const } : {}),
      };
      return {
        width: LEAF_WIDTH,
        height: LEAF_HEIGHT,
        nodes: [leaf],
        edges: [],
        entry: node.id,
        exit: node.id,
      };
    }
  }
}

function* specNodes(node: SpecNode): Generator<SpecNode> {
  yield node;
  if (node.type === "sequence") for (const step of node.steps) yield* specNodes(step);
  if (node.type === "loop" || node.type === "map") yield* specNodes(node.body);
}

/** Every node of the spec, depth first in run order, sequences included. */
export function allSpecNodes(spec: WorkflowSpec): SpecNode[] {
  return [...specNodes(spec.root)];
}

/** The graph of `spec`. A reduce is linked to the map it combines, labelled "reduces". */
export function specToGraph(spec: WorkflowSpec): SpecGraph {
  const { nodes, edges } = layout(spec.root, undefined);
  for (const node of specNodes(spec.root)) {
    if (node.type !== "reduce") continue;
    const id = `${node.from}->${node.id}`;
    const existing = edges.find((e) => e.id === id);
    if (existing) {
      existing.label = "reduces";
    } else {
      // Not the step right before it: a dashed link, apart from the run order.
      edges.push({
        id,
        source: node.from,
        target: node.id,
        type: "smoothstep",
        label: "reduces",
        style: { strokeDasharray: "4 4" },
      });
    }
  }
  return { nodes, edges };
}
