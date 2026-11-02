import type { NodeKind, SpecNode, WorkflowSpec } from "@/runs/graph/spec-graph";

import { allPlaces, type Place } from "./edits";

/** One value that differs between two versions, at its parameter path (`instructions`,
 * `classifier.instructions`, `routes[1].when`); `undefined` where it is unset. */
export interface ValueChange {
  path: string;
  before: unknown;
  after: unknown;
}

/** How a node of the newer version differs from the older (5.7). A node both moved and changed
 * is `changed`, with `moved` set. */
export type NodeChange =
  | { kind: "added" }
  | { kind: "moved" }
  | { kind: "changed"; moved: boolean; changes: ValueChange[] };

export interface SpecDiff {
  /** The nodes of the newer version that are new, moved or changed, by id. */
  nodes: Map<string, NodeChange>;
  /** The nodes of the older version that are gone, in its run order. */
  removed: { id: string; type: NodeKind }[];
  /** The workflow's own fields that changed: name, description, budget. */
  document: ValueChange[];
}

/** The fields of a node that hold nodes: what changes there is a node added, removed or moved,
 * never a parameter. A route's `then` is in its router's `routes`. */
const SLOTS = new Set(["steps", "branches", "body", "default"]);
const DOCUMENT_FIELDS = ["name", "description", "budget_usd"] as const;

/** What changed from `before` to `after`, node by node. Nodes are matched by id, which graph
 * operations never change (5.1). */
export function diffSpecs(before: WorkflowSpec, after: WorkflowSpec): SpecDiff {
  const old = new Map(allPlaces(before).map((p) => [p.node.id, p]));
  const now = allPlaces(after);
  const reordered = reorderedIds(old, now);
  const nodes = new Map<string, NodeChange>();
  for (const place of now) {
    const was = old.get(place.node.id);
    if (!was) {
      nodes.set(place.node.id, { kind: "added" });
      continue;
    }
    const moved = slotOf(was) !== slotOf(place) || reordered.has(place.node.id);
    const changes = valueChanges(params(was.node), params(place.node));
    if (changes.length > 0) nodes.set(place.node.id, { kind: "changed", moved, changes });
    else if (moved) nodes.set(place.node.id, { kind: "moved" });
  }
  const ids = new Set(now.map((p) => p.node.id));
  const removed = [...old.values()]
    .filter((p) => !ids.has(p.node.id))
    .map((p) => ({ id: p.node.id, type: p.node.type }));
  const document = DOCUMENT_FIELDS.flatMap((field) =>
    valueChanges({ [field]: before[field] }, { [field]: after[field] }),
  );
  return { nodes, removed, document };
}

/** The diff as one line: "2 added · 1 changed · 1 removed", or "No changes". */
export function summarizeDiff(diff: SpecDiff): string {
  const count = { added: 0, changed: 0, moved: 0 };
  for (const change of diff.nodes.values()) count[change.kind] += 1;
  const parts = [
    count.added ? `${count.added} added` : null,
    count.changed ? `${count.changed} changed` : null,
    count.moved ? `${count.moved} moved` : null,
    diff.removed.length ? `${diff.removed.length} removed` : null,
    diff.document.length
      ? `${diff.document.length} workflow ${diff.document.length === 1 ? "field" : "fields"}`
      : null,
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join(" · ") : "No changes";
}

/** The container and slot a node is in (a route counts as its own slot). */
function slotOf(place: Place): string {
  return `${place.parent?.id ?? ""}/${place.slot}/${place.route ?? ""}`;
}

/** The nodes that stayed in their list (a sequence's steps, a parallel's branches) but not in
 * its order: those off the longest run the two orders share, so one step moved past others marks
 * that step only, and a step added or removed next to it none. */
function reorderedIds(old: Map<string, Place>, now: Place[]): Set<string> {
  const moved = new Set<string>();
  const seen = new Set<string>();
  for (const place of now) {
    const slot = slotOf(place);
    if (seen.has(slot)) continue;
    seen.add(slot);
    const stayed = place.siblings.filter((id) => {
      const was = old.get(id);
      return was !== undefined && slotOf(was) === slot;
    });
    if (stayed.length < 2) continue;
    const before = old.get(stayed[0])!.siblings.filter((id) => stayed.includes(id));
    const common = new Set(longestCommon(before, stayed));
    for (const id of stayed) if (!common.has(id)) moved.add(id);
  }
  return moved;
}

/** The longest subsequence of both lists (each holds the same ids, once each). */
function longestCommon(a: string[], b: string[]): string[] {
  const table = a.map(() => new Array<number>(b.length + 1).fill(0));
  table.push(new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] =
        a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const out: string[] = [];
  for (let i = 0, j = 0; i < a.length && j < b.length;) {
    if (a[i] === b[j]) {
      out.push(a[i]);
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) i++;
    else j++;
  }
  return out;
}

/** A node's parameters: everything but the nodes it holds. */
function params(node: SpecNode): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(node)) {
    if (SLOTS.has(key)) continue;
    out[key] =
      key === "routes" && Array.isArray(value)
        ? value.map((route: Record<string, unknown>) =>
            Object.fromEntries(Object.entries(route).filter(([field]) => field !== "then")),
          )
        : value;
  }
  return out;
}

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The leaf values that differ, by path. Objects are compared field by field, and lists of
 * objects of the same length item by item; any other value (a list of tools) as a whole. */
function valueChanges(before: unknown, after: unknown, path = ""): ValueChange[] {
  if (isObject(before) && isObject(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
    return keys.flatMap((key) =>
      valueChanges(before[key], after[key], path ? `${path}.${key}` : key),
    );
  }
  if (
    Array.isArray(before) &&
    Array.isArray(after) &&
    before.length === after.length &&
    before.every(isObject) &&
    after.every(isObject)
  ) {
    return before.flatMap((item, i) => valueChanges(item, after[i], `${path}[${i}]`));
  }
  return same(before, after) ? [] : [{ path, before, after }];
}

function same(a: unknown, b: unknown): boolean {
  // `null` and unset are the same to the spec: a set to `null` unsets it.
  if ((a ?? null) === null && (b ?? null) === null) return true;
  return JSON.stringify(a) === JSON.stringify(b);
}
