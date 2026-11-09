import type { components } from "@/api/schema";
import {
  allSpecNodes,
  DEFAULT_ROUTE,
  routesOf,
  type SpecNode,
  type WorkflowSpec,
} from "@/runs/graph/spec-graph";

import type { NodeManifest } from "./node-types";
import { applyOps, type GraphOp } from "./ops";
import { portMismatches, type Mismatch } from "./ports";

/**
 * The builder's edits (5.2), each made of the graph operations that do it. An edit is one undo
 * step; Save sends every edit's ops as one batch. Any node can be edited, at any depth (5.5); an
 * edit never leaves a container empty or a parallel with one branch, which only the server's schema
 * check would refuse, and never makes a connection whose ports do not fit (5.6).
 */

export interface Edit {
  /** What the edit did, for the undo button's label and the toast after a rebase. */
  label: string;
  ops: GraphOp[];
  /** Edits with the same key in a row are one undo step: the later replaces the earlier (typing
   * in one field of the side panel). */
  key?: string;
  /** The node the edit added, moved or put in, for the focus to go to. */
  focus?: string;
}

type AddNode = components["schemas"]["AddNode"];
type Json = Record<string, unknown>;

/** The nodes under `node`, itself first, found through each manifest's `slots` (`steps`,
 * `body`, `routes[].then`); a kind with no manifest is a leaf. */
function* nodesUnder(node: Json, manifests: Map<string, NodeManifest>): Generator<Json> {
  yield node;
  for (const slot of manifests.get(String(node.type))?.slots ?? []) {
    const [head, field] = slot.split("[].");
    const held = field
      ? ((node[head] as Json[] | undefined) ?? []).map((item) => item[field])
      : [node[head]];
    for (const value of held.flat()) {
      if (value && typeof value === "object") yield* nodesUnder(value as Json, manifests);
    }
  }
}

/**
 * A new node from `kind`'s manifest: its `default` with a fresh id for every node in it (the
 * first free `<kind>_<n>` in `spec`: `agent_1`, `agent_2`, …) and its `fill` applied, added
 * after the step `afterId` (`null`: first).
 */
export function newNode(
  spec: WorkflowSpec,
  kind: string,
  manifests: NodeManifest[],
  afterId: string | null = null,
): AddNode["node"] {
  const byKind = new Map(manifests.map((m) => [m.kind, m]));
  const manifest = byKind.get(kind);
  if (!manifest) throw new Error(`There is no node type ${kind}.`);
  const taken = new Set(
    [...nodesUnder(spec.root as unknown as Json, byKind)].map((n) => String(n.id)),
  );
  const node = structuredClone(manifest.default) as Json;
  for (const n of nodesUnder(node, byKind)) {
    let i = 1;
    while (taken.has(`${n.type}_${i}`)) i++;
    n.id = `${n.type}_${i}`;
    taken.add(n.id as string);
  }
  for (const [param, fill] of Object.entries(manifest.fill ?? {})) {
    if (fill === "previous_step" && afterId !== null) node[param] = afterId;
  }
  return node as AddNode["node"];
}

/** The steps of the root sequence (none when the root is not one). */
export function rootSteps(spec: WorkflowSpec): SpecNode[] {
  return spec.root.type === "sequence" ? spec.root.steps : [];
}

/** The first `<kind>_<n>` not in `taken`. */
function freeId(taken: Set<string>, kind: string): string {
  let i = 1;
  while (taken.has(`${kind}_${i}`)) i++;
  return `${kind}_${i}`;
}

const idsIn = (node: SpecNode) => allSpecNodes({ root: node } as WorkflowSpec).map((n) => n.id);

/** Where a node is in the spec: the root, a sequence's step, a parallel's branch, a loop's,
 * map's or orchestrator's body, or what runs on a router's route (`route`: its id, or `default`). */
export interface Place {
  node: SpecNode;
  parent: SpecNode | null;
  slot: "root" | "steps" | "branches" | "body" | "route";
  /** The ids of the list the node is in (a sequence's steps, a parallel's branches); only its
   * own id in a slot that holds one node. */
  siblings: string[];
  index: number;
  route?: string;
}

function* places(place: Place): Generator<Place> {
  yield place;
  const { node } = place;
  const list = (slot: "steps" | "branches", nodes: SpecNode[]): Place[] =>
    nodes.map((child, index) => ({
      node: child,
      parent: node,
      slot,
      siblings: nodes.map((n) => n.id),
      index,
    }));
  let children: Place[] = [];
  if (node.type === "sequence") children = list("steps", node.steps);
  if (node.type === "parallel") children = list("branches", node.branches);
  if (node.type === "loop" || node.type === "map" || node.type === "orchestrator") {
    children = [
      { node: node.body, parent: node, slot: "body", siblings: [node.body.id], index: 0 },
    ];
  }
  if (node.type === "router") {
    children = routesOf(node).map(([route, child]) => ({
      node: child,
      parent: node,
      slot: "route",
      siblings: [child.id],
      index: 0,
      route,
    }));
  }
  for (const child of children) yield* places(child);
}

/** Where every node of the spec is, depth first in run order. */
export function allPlaces(spec: WorkflowSpec): Place[] {
  const root: Place = {
    node: spec.root,
    parent: null,
    slot: "root",
    siblings: [spec.root.id],
    index: 0,
  };
  return [...places(root)];
}

/** Where `nodeId` is, or `null` when the spec has no such node. */
export function placeOf(spec: WorkflowSpec, nodeId: string): Place | null {
  return allPlaces(spec).find((place) => place.node.id === nodeId) ?? null;
}

/** Why the node at `place` cannot leave it (be removed or moved away), as a sentence for its
 * menu; `null` when it can. A container is never left empty: the spec's schema needs a step in
 * every sequence, a body in every loop and map, a node on every route and two parallel branches,
 * and only the server checks it. */
export function stayReason(place: Place): string | null {
  switch (place.slot) {
    case "root":
      return "The workflow's root stays.";
    case "steps":
      return place.siblings.length > 1 ? null : "The only step here stays; replace it instead.";
    case "branches":
      return place.siblings.length > 2 ? null : "A parallel needs at least two branches.";
    case "body": {
      const kind = place.parent?.type ?? "container";
      return `${/^[aeiou]/.test(kind) ? "An" : "A"} ${kind} needs a body; replace it instead.`;
    }
    case "route":
      return place.route === DEFAULT_ROUTE ? null : "A route needs a step; replace it instead.";
  }
}

/** Add a new `kind` node, from its manifest, after the node `afterId`, or first in the root
 * sequence when `null`. After a node that is not a sequence's step (a body, a branch, a route)
 * the two go in a new sequence that takes its place. */
export function addStep(
  spec: WorkflowSpec,
  afterId: string | null,
  kind: string,
  manifests: NodeManifest[],
): Edit {
  const node = newNode(spec, kind, manifests, afterId);
  const label = `Add ${node.id}`;
  if (afterId === null) {
    return {
      label,
      focus: node.id,
      ops: [{ op: "addNode", node, at: { parent: spec.root.id, index: 0 } }],
    };
  }
  if (placeOf(spec, afterId)?.slot === "steps") {
    return { label, focus: node.id, ops: [{ op: "addNode", node, at: { after: afterId } }] };
  }
  const taken = new Set([...idsIn(spec.root), ...idsIn(node as SpecNode)]);
  return {
    label,
    focus: node.id,
    ops: [
      { op: "addNode", node },
      { op: "connect", from: afterId, to: node.id, sequence_id: freeId(taken, "sequence") },
    ],
  };
}

/** Add a new `kind` node, from its manifest, as the last branch of the parallel `parallelId`. */
export function addBranch(
  spec: WorkflowSpec,
  parallelId: string,
  kind: string,
  manifests: NodeManifest[],
): Edit {
  const node = newNode(spec, kind, manifests);
  return {
    label: `Add ${node.id} as a branch of ${parallelId}`,
    focus: node.id,
    ops: [{ op: "addNode", node, at: { parent: parallelId } }],
  };
}

/** Move a sequence's step one place up or down: one `connect` (moving the first step down puts
 * it after the second; moving a step up puts the step before it after it). `null` when it cannot
 * move that way, or is not a sequence's step. */
export function moveStep(
  spec: WorkflowSpec,
  nodeId: string,
  direction: "up" | "down",
): Edit | null {
  const place = placeOf(spec, nodeId);
  if (place?.slot !== "steps") return null;
  const { siblings: ids, index: i } = place;
  const label = `Move ${nodeId} ${direction}`;
  if (direction === "down") {
    const next = ids[i + 1];
    return next ? { label, focus: nodeId, ops: [{ op: "connect", from: next, to: nodeId }] } : null;
  }
  if (i === 0) return null;
  // Up: the step before it goes after it; for the second step that is the only way to the top.
  return { label, focus: nodeId, ops: [{ op: "connect", from: nodeId, to: ids[i - 1] }] };
}

/** Where a node can move to: right after another node, or as a new branch of a parallel. */
export type MoveTarget = { after: string } | { branchOf: string };

/** Every place `nodeId` can move to, in run order; none when it cannot leave where it is
 * (`stayReason`). Not after itself or a node under it (a node cannot hold itself), a sequence
 * (its steps are the targets) or the step right before it (it is there), and not a new branch
 * of the parallel it is a branch of. */
export function moveTargets(spec: WorkflowSpec, nodeId: string): MoveTarget[] {
  const place = placeOf(spec, nodeId);
  if (!place || stayReason(place) !== null) return [];
  const under = new Set(idsIn(place.node));
  const before = place.slot === "steps" && place.index > 0 ? place.siblings[place.index - 1] : null;
  const targets: MoveTarget[] = [];
  for (const node of allSpecNodes(spec)) {
    if (under.has(node.id) || node.type === "sequence") continue;
    if (node.id !== before) targets.push({ after: node.id });
    const ownParallel = place.slot === "branches" && place.parent?.id === node.id;
    if (node.type === "parallel" && !ownParallel) targets.push({ branchOf: node.id });
  }
  return targets;
}

/** Move `nodeId`, with what is under it, to `target`: one `connect` (in a new sequence when the
 * node it follows is not a sequence's step), or for a new branch a `removeNode` and an `addNode`
 * of the same nodes. */
export function moveTo(spec: WorkflowSpec, nodeId: string, target: MoveTarget): Edit {
  if ("branchOf" in target) {
    const node = placeOf(spec, nodeId)?.node;
    if (!node) throw new Error(`There is no node ${nodeId}.`);
    return {
      label: `Move ${nodeId} to a branch of ${target.branchOf}`,
      focus: nodeId,
      ops: [
        { op: "removeNode", node_id: nodeId },
        { op: "addNode", node: node as AddNode["node"], at: { parent: target.branchOf } },
      ],
    };
  }
  const connect =
    placeOf(spec, target.after)?.slot === "steps"
      ? { op: "connect" as const, from: target.after, to: nodeId }
      : {
          op: "connect" as const,
          from: target.after,
          to: nodeId,
          sequence_id: freeId(new Set(idsIn(spec.root)), "sequence"),
        };
  return { label: `Move ${nodeId} after ${target.after}`, focus: nodeId, ops: [connect] };
}

/** Put a new `kind` node, from its manifest, where `nodeId` is, which goes with what is under
 * it: a `removeNode` and an `addNode` in one batch, so a body or a route is never empty. `null`
 * for the root. */
export function replaceNode(
  spec: WorkflowSpec,
  nodeId: string,
  kind: string,
  manifests: NodeManifest[],
): Edit | null {
  const place = placeOf(spec, nodeId);
  if (!place?.parent) return null;
  const parent = place.parent.id;
  const before = place.slot === "steps" && place.index > 0 ? place.siblings[place.index - 1] : null;
  const node = newNode(spec, kind, manifests, before);
  const at =
    place.slot === "steps" || place.slot === "branches"
      ? { parent, index: place.index }
      : place.slot === "route"
        ? { parent, route: place.route }
        : { parent };
  return {
    label: `Replace ${nodeId} with ${node.id}`,
    focus: node.id,
    ops: [
      { op: "removeNode", node_id: nodeId },
      { op: "addNode", node, at },
    ],
  };
}

export function removeStep(nodeId: string): Edit {
  return { label: `Remove ${nodeId}`, ops: [{ op: "removeNode", node_id: nodeId }] };
}

/** How many nodes go with `node` when it is removed, itself included. */
export function subtreeSize(node: SpecNode): number {
  return allSpecNodes({ root: node } as WorkflowSpec).length;
}

const edgeKey = (m: Mismatch) => `${m.producer}>${m.consumer}`;

/** The incompatible connections `edit` would make in `spec` that it does not have yet (5.6); none
 * when it keeps or removes the ones it has, or does not apply. */
export function newMismatches(spec: WorkflowSpec, edit: Edit): Mismatch[] {
  let after: WorkflowSpec;
  try {
    after = applyOps(spec, edit.ops);
  } catch {
    return [];
  }
  const had = new Set(portMismatches(spec).map(edgeKey));
  return portMismatches(after).filter((m) => !had.has(edgeKey(m)));
}

/** What an orchestrator's worker may hold (6.1): agents and tools, alone or in a sequence. */
const WORKER_KINDS = new Set(["agent", "tool", "sequence"]);

/** The nodes of `spec` inside an orchestrator's worker that it may not hold, as
 * `<node> in <orchestrator>`, the mirror of validation's `not_allowed_in_orchestrator` by kind
 * (a publishing or repo-creating tool is left to the server's check). */
function misplacedInWorkers(spec: WorkflowSpec): Map<string, string> {
  const found = new Map<string, string>();
  for (const node of allSpecNodes(spec)) {
    if (node.type !== "orchestrator") continue;
    for (const inner of allSpecNodes({ root: node.body } as WorkflowSpec)) {
      if (!WORKER_KINDS.has(inner.type)) found.set(inner.id, node.id);
    }
  }
  return found;
}

/** Why `edit` is not offered, as a sentence for its menu item: a node it would put in an
 * orchestrator's worker that the worker may not hold, else the first connection it would make
 * whose ports do not fit; `null` when it may be made (or when there is no edit). */
export function blockReason(spec: WorkflowSpec, edit: Edit | null): string | null {
  if (!edit) return null;
  let after: WorkflowSpec | null = null;
  try {
    after = applyOps(spec, edit.ops);
  } catch {
    after = null;
  }
  if (after) {
    const had = misplacedInWorkers(spec);
    for (const [nodeId, orchestrator] of misplacedInWorkers(after)) {
      if (had.get(nodeId) === orchestrator) continue;
      const kind = allSpecNodes(after).find((n) => n.id === nodeId)?.type ?? "node";
      return `The worker of '${orchestrator}' holds only agents and tools, not a ${kind}.`;
    }
  }
  return newMismatches(spec, edit)[0]?.reason ?? null;
}
