import type { components } from "@/api/schema";
import { allSpecNodes, type SpecNode, type WorkflowSpec } from "@/runs/graph/spec-graph";

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

/** The kinds the "Add step" menu offers until the manifest palette (5.3) replaces it. */
export const NEW_KINDS = ["agent", "tool", "gate"] as const;
export type NewKind = (typeof NEW_KINDS)[number];

type AddNode = components["schemas"]["AddNode"];

/** A new node of `kind` with defaults that match the schema, under an id not used in `spec`:
 * `agent_1`, `agent_2`, … */
export function newNode(spec: WorkflowSpec, kind: NewKind): AddNode["node"] {
  const ids = new Set(allSpecNodes(spec).map((n) => n.id));
  let n = 1;
  while (ids.has(`${kind}_${n}`)) n++;
  const id = `${kind}_${n}`;
  switch (kind) {
    case "agent":
      return { type: "agent", id, role: "Agent", instructions: "Describe what this agent does." };
    case "tool":
      return { type: "tool", id, tool: "repo.list_files" };
    case "gate":
      return { type: "gate", id, title: "Approve" };
  }
}

/** The steps the builder edits: those of the root sequence (none when the root is not one). */
export function rootSteps(spec: WorkflowSpec): SpecNode[] {
  return spec.root.type === "sequence" ? spec.root.steps : [];
}

/** Add a new `kind` node after the step `afterId`, or first when it is `null`. */
export function addStep(spec: WorkflowSpec, afterId: string | null, kind: NewKind): Edit {
  const node = newNode(spec, kind);
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
