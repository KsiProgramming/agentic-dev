import type { components } from "@/api/schema";
import { allSpecNodes, type SpecNode, type WorkflowSpec } from "@/runs/graph/spec-graph";

import type { NodeManifest } from "./node-types";
import type { GraphOp } from "./ops";

/**
 * The builder's edits (5.2), each made of the graph operations that do it. An edit is one undo
 * step; Save sends every edit's ops as one batch. Only the steps of the root sequence are edited
 * here; inside containers comes with 5.5.
 */

export interface Edit {
  /** What the edit did, for the undo button's label and the toast after a rebase. */
  label: string;
  ops: GraphOp[];
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
 * first free `<kind>_<n>` in `spec`: `agent_1`, `agent_2`, �) and its `fill` applied, added
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

/** The steps the builder edits: those of the root sequence (none when the root is not one). */
export function rootSteps(spec: WorkflowSpec): SpecNode[] {
  return spec.root.type === "sequence" ? spec.root.steps : [];
}

/** Add a new `kind` node, from its manifest, after the step `afterId`, or first when `null`. */
export function addStep(
  spec: WorkflowSpec,
  afterId: string | null,
  kind: string,
  manifests: NodeManifest[],
): Edit {
  const node = newNode(spec, kind, manifests, afterId);
  const at = afterId === null ? { parent: spec.root.id, index: 0 } : { after: afterId };
  return { label: `Add ${node.id}`, ops: [{ op: "addNode", node, at }] };
}

/** Move a root step one place up or down: one `connect` (moving the first step down puts it
 * after the second; moving a step up puts the step before it after it). `null` when it cannot
 * move that way. */
export function moveStep(
  spec: WorkflowSpec,
  nodeId: string,
  direction: "up" | "down",
): Edit | null {
  const ids = rootSteps(spec).map((s) => s.id);
  const i = ids.indexOf(nodeId);
  if (i < 0) return null;
  const label = `Move ${nodeId} ${direction}`;
  if (direction === "down") {
    const next = ids[i + 1];
    return next ? { label, ops: [{ op: "connect", from: next, to: nodeId }] } : null;
  }
  if (i === 0) return null;
  // Up: the step before it goes after it; for the second step that is the only way to the top.
  return { label, ops: [{ op: "connect", from: nodeId, to: ids[i - 1] }] };
}

export function removeStep(nodeId: string): Edit {
  return { label: `Remove ${nodeId}`, ops: [{ op: "removeNode", node_id: nodeId }] };
}

/** Set the workflow's `name` or `description`; an empty description unsets it. */
export function setDocument(field: "name" | "description", value: string): Edit {
  const label = field === "name" ? "Rename the workflow" : "Change the description";
  const set = field === "description" && value.trim() === "" ? null : value;
  return { label, ops: [{ op: "setParam", path: field, value: set }] };
}

/** How many nodes go with `node` when it is removed, itself included. */
export function subtreeSize(node: SpecNode): number {
  return allSpecNodes({ root: node } as WorkflowSpec).length;
}
