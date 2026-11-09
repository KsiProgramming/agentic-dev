import { calledRoot } from "../calls";
import type { MapNode } from "./spec-tree";
import { nodeDetail, routeNodeId, routesOf, type SpecNode, type WorkflowSpec } from "./spec-graph";

/**
 * A workflow spec as a flow read left to right (5.9): every node's card in a grid cell, and the
 * edges between them. Workflows are series-parallel, so the layout follows from the spec tree in
 * one pass, with no layout library:
 *
 * - a sequence is its steps left to right, each step's exits joined to the next step; it wraps
 *   like text within the columns it has, never splitting a step;
 * - a parallel forks into one lane per branch, a router into one lane per route (its edges
 *   carry the route's name), and their lanes' exits all join the next step;
 * - a map's or an orchestrator's body is one framed lane ("Each item", "Each task");
 * - a loop's body is a framed lane ("Repeats until …") whose end has a back edge to the loop;
 * - a subflow's called workflow (in a run, `calledRoot`) is a framed lane; in the builder a
 *   subflow is one card.
 *
 * Cells, not pixels: a card may be taller than another (an orchestrator's tasks on the run map),
 * and the grid sizes its rows. The renderer measures the cards to draw the edges.
 */

export interface FlowCard {
  node: MapNode;
  /** The grid cell, from 0. */
  col: number;
  row: number;
}

/** `wrap`: the flow going on at the start of a sequence's next row. */
export type FlowEdgeKind = "flow" | "fork" | "back" | "wrap";

export interface FlowEdge {
  from: string;
  to: string;
  kind: FlowEdgeKind;
  /** A route's name on a router's fork. */
  label: string | null;
  /** For a router's fork: its route's `routeNodeId`, so the run map can dash a route not taken. */
  route: string | null;
}

/** A framed lane: a map's, an orchestrator's or a loop's body, or the workflow a subflow called. */
export interface FlowLane {
  id: string;
  col: number;
  row: number;
  cols: number;
  rows: number;
  label: string;
}

export interface FlowLayout {
  cards: FlowCard[];
  edges: FlowEdge[];
  lanes: FlowLane[];
  cols: number;
  rows: number;
}

/** A node laid out from cell (0, 0), with the card the flow enters by and those it leaves by. */
interface Part extends FlowLayout {
  entry: string;
  exits: string[];
}

interface Lane {
  node: SpecNode;
  label: string | null;
  route: string | null;
  frame: string | null;
}

function card(node: SpecNode): MapNode {
  return { id: node.id, name: node.id, kind: node.type, detail: nodeDetail(node), children: [] };
}

/**
 * The flow of `spec`, cards in run order. With `maxCols`, every sequence wraps within the columns
 * it has (the pane's, less those of the containers it is in): a step that would go past them
 * starts a new row under the sequence's first column, joined by a `wrap` edge. A step is never
 * split, so one wider than the room left has a row of its own and scrolls.
 */
export function flowLayout(spec: WorkflowSpec, maxCols?: number): FlowLayout {
  const { cards, edges, lanes, cols, rows } = laid(spec.root, maxCols ?? Infinity);
  return { cards, edges, lanes, cols, rows };
}

function empty(entry: string): Part {
  return { cards: [], edges: [], lanes: [], cols: 0, rows: 0, entry, exits: [] };
}

/** Adds `part`, moved to cell (`col`, `row`), to `out`. */
function add(out: Part, part: Part, col: number, row: number) {
  out.cards.push(...part.cards.map((c) => ({ ...c, col: c.col + col, row: c.row + row })));
  out.lanes.push(...part.lanes.map((l) => ({ ...l, col: l.col + col, row: l.row + row })));
  out.edges.push(...part.edges);
}

/** `node`'s card, and its lanes to its right, stacked top to bottom, in `room` columns. */
function container(node: SpecNode, lanes: Lane[], room: number): Part {
  const out = empty(node.id);
  out.cards.push({ node: card(node), col: 0, row: 0 });
  let next = 0;
  let widest = 0;
  for (const lane of lanes) {
    const part = laid(lane.node, Math.max(1, room - 1));
    add(out, part, 1, next);
    out.edges.push({
      from: node.id,
      to: part.entry,
      kind: "fork",
      label: lane.label,
      route: lane.route,
    });
    if (lane.frame) {
      out.lanes.push({
        id: node.id,
        col: 1,
        row: next,
        cols: part.cols,
        rows: part.rows,
        label: lane.frame,
      });
    }
    out.exits.push(...part.exits);
    widest = Math.max(widest, part.cols);
    next += part.rows;
  }
  out.cols = 1 + widest;
  out.rows = Math.max(1, next);
  return out;
}

/** `node` laid out from cell (0, 0) in `room` columns. */
function laid(node: SpecNode, room: number): Part {
  switch (node.type) {
    case "sequence": {
      const out = empty(node.id);
      let at = 0;
      let top = 0;
      let lineRows = 1;
      let first = true;
      for (const step of node.steps) {
        let part = laid(step, Math.max(1, room - at));
        // A step that does not fit what is left of the row, or would only fit it by wrapping
        // more than it would on a row of its own, starts the next row.
        const whole = at > 0 ? laid(step, room) : part;
        const wraps = at > 0 && (at + part.cols > room || part.rows > whole.rows);
        if (wraps) {
          top += lineRows;
          at = 0;
          lineRows = 1;
          part = whole;
        }
        add(out, part, at, top);
        if (first) out.entry = part.entry;
        for (const from of out.exits) {
          out.edges.push({
            from,
            to: part.entry,
            kind: wraps ? "wrap" : "flow",
            label: null,
            route: null,
          });
        }
        first = false;
        out.exits = part.exits;
        at += part.cols;
        lineRows = Math.max(lineRows, part.rows);
        out.cols = Math.max(out.cols, at);
      }
      out.rows = top + lineRows;
      return out;
    }
    case "parallel":
      return container(
        node,
        node.branches.map((branch) => ({ node: branch, label: null, route: null, frame: null })),
        room,
      );
    case "router":
      return container(
        node,
        routesOf(node).map(([routeId, route]) => ({
          node: route,
          label: routeId,
          route: routeNodeId(node.id, routeId),
          frame: null,
        })),
        room,
      );
    case "map":
    case "orchestrator":
      return container(
        node,
        [
          {
            node: node.body,
            label: null,
            route: null,
            frame: node.type === "map" ? "Each item" : "Each task",
          },
        ],
        room,
      );
    case "loop": {
      // The lane says when it stops; the back edge from its end says it goes round again.
      const out = container(
        node,
        [{ node: node.body, label: null, route: null, frame: `Repeats until ${node.until}` }],
        room,
      );
      for (const from of out.exits) {
        out.edges.push({ from, to: node.id, kind: "back", label: null, route: null });
      }
      return out;
    }
    case "subflow": {
      const called = calledRoot(node);
      if (!called) break;
      return container(
        node,
        [
          {
            node: called,
            label: null,
            route: null,
            frame: `Calls ${node.workflow.id} · version ${node.workflow.version}`,
          },
        ],
        room,
      );
    }
    default:
      break;
  }
  const out = empty(node.id);
  out.cards.push({ node: card(node), col: 0, row: 0 });
  out.exits = [node.id];
  out.cols = 1;
  out.rows = 1;
  return out;
}
