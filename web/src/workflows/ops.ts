import type { components } from "@/api/schema";

/**
 * Graph operations (5.1) applied in the browser, so the builder shows edits before they are
 * saved and can apply them again on a newer version after a conflict (5.2). It mirrors
 * `agentic_engine.spec.ops.apply_ops` case for case (the shared fixtures in
 * `schemas/fixtures/graph-ops.json` keep the two alike), except the `schema` check, which only the
 * server makes: the server's answer is the truth, this is a preview.
 */

export type GraphOp =
  | components["schemas"]["AddNode"]
  | components["schemas"]["RemoveNode"]
  | components["schemas"]["Connect"]
  | components["schemas"]["Disconnect"]
  | components["schemas"]["SetParam"];
export type OpErrorCode = components["schemas"]["OpErrorDetail"]["code"];

/** Why a batch cannot apply: the op at `op_index` (`null`: the batch's result) and its node. */
export class OpError extends Error {
  constructor(
    readonly code: OpErrorCode,
    message: string,
    readonly op_index: number | null,
    readonly node_id: string | null,
  ) {
    super(message);
    this.name = "OpError";
  }
}

type Json = Record<string, unknown>;

const SINGLE_SLOTS = ["body", "default"] as const;
const LIST_SLOTS: Record<string, string> = { sequence: "steps", parallel: "branches" };
const NODE_SLOTS = new Set(["steps", "branches", "body", "default"]);
const DOCUMENT_PARAMS = new Set(["name", "description", "budget_usd"]);
const DEFAULT_ROUTE = "default";

/** Where a node is: `holder[key]` is it, under `parent`'s field `slot`. */
interface Place {
  holder: Json | unknown[];
  key: string | number;
  parent: Json | null;
  slot: string | null;
}

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function* walk(node: Json, place: Place): Generator<[Json, Place]> {
  yield [node, place];
  const slot = LIST_SLOTS[String(node.type)];
  const children = slot ? node[slot] : undefined;
  if (slot && Array.isArray(children)) {
    for (let i = 0; i < children.length; i++) {
      const child: unknown = children[i];
      if (isObject(child)) yield* walk(child, { holder: children, key: i, parent: node, slot });
    }
  }
  for (const single of SINGLE_SLOTS) {
    const child = node[single];
    if (isObject(child))
      yield* walk(child, { holder: node, key: single, parent: node, slot: single });
  }
  if (node.type === "router" && Array.isArray(node.routes)) {
    for (const route of node.routes) {
      if (isObject(route) && isObject(route.then)) {
        yield* walk(route.then, { holder: route, key: "then", parent: node, slot: "then" });
      }
    }
  }
}

/** A spec being edited, with the nodes detached so far. */
class Tree {
  readonly doc: Json;
  readonly pool: Json = {};

  constructor(spec: unknown) {
    this.doc = structuredClone(spec) as Json;
  }

  *places(): Generator<[Json, Place]> {
    if (isObject(this.doc.root)) {
      yield* walk(this.doc.root, { holder: this.doc, key: "root", parent: null, slot: null });
    }
    for (const [key, node] of Object.entries(this.pool)) {
      if (isObject(node)) yield* walk(node, { holder: this.pool, key, parent: null, slot: null });
    }
  }

  find(nodeId: string): [Json, Place] | null {
    for (const found of this.places()) if (found[0].id === nodeId) return found;
    return null;
  }

  ids(): Set<string> {
    const ids = new Set<string>();
    for (const [node] of this.places()) if (typeof node.id === "string") ids.add(node.id);
    return ids;
  }
}

/** `spec` with `ops` applied in order; `spec` is not changed. Throws `OpError`. */
export function applyOps<S>(spec: S, ops: readonly GraphOp[]): S {
  const tree = new Tree(spec);
  ops.forEach((op, index) => {
    switch (op.op) {
      case "addNode":
        return add(tree, op, index);
      case "removeNode":
        return void takeOut(tree, op.node_id, index);
      case "connect":
        return connect(tree, op, index);
      case "disconnect":
        return disconnect(tree, op, index);
      case "setParam":
        return setParam(tree, op, index);
    }
  });
  checkResult(tree);
  return tree.doc as S;
}

function subtreeIds(node: Json): string[] {
  return [...walk(node, { holder: {}, key: "", parent: null, slot: null })].map(([n]) =>
    String(n.id),
  );
}

function duplicate(nodeId: string, index: number): OpError {
  return new OpError(
    "duplicate_node_id",
    `node id '${nodeId}' is already used; node ids must be unique`,
    index,
    nodeId,
  );
}

function add(tree: Tree, op: components["schemas"]["AddNode"], index: number): void {
  const node = structuredClone(op.node) as Json;
  const taken = tree.ids();
  const seen = new Set<string>();
  for (const nodeId of subtreeIds(node)) {
    if (taken.has(nodeId) || seen.has(nodeId)) throw duplicate(nodeId, index);
    seen.add(nodeId);
  }
  if (!op.at) tree.pool[String(node.id)] = node;
  else if ("after" in op.at) insertAfter(tree, op.at.after, node, null, index);
  else insertInto(tree, op.at, node, index);
}

function require(tree: Tree, nodeId: string, index: number): [Json, Place] {
  const found = tree.find(nodeId);
  if (!found) throw new OpError("unknown_node", `there is no node '${nodeId}'`, index, nodeId);
  return found;
}

function setAt(place: Place, value: unknown): void {
  if (Array.isArray(place.holder)) place.holder[place.key as number] = value;
  else place.holder[place.key as string] = value;
}

function insertAfter(
  tree: Tree,
  after: string,
  node: Json,
  sequenceId: string | null | undefined,
  index: number,
): void {
  const [target, place] = require(tree, after, index);
  if (place.slot === "steps") {
    (place.holder as unknown[]).splice((place.key as number) + 1, 0, node);
    return;
  }
  if (!sequenceId) {
    throw new OpError(
      "not_in_sequence",
      `${String(target.type)} '${after}' is not a step of a sequence; give \`sequence_id\` to wrap it in a new sequence`,
      index,
      after,
    );
  }
  if (tree.ids().has(sequenceId)) throw duplicate(sequenceId, index);
  setAt(place, { type: "sequence", id: sequenceId, steps: [target, node] });
}

function insertInto(
  tree: Tree,
  at: components["schemas"]["Into"],
  node: Json,
  index: number,
): void {
  const [parent] = require(tree, at.parent, index);
  const kind = String(parent.type);
  const refuse = (code: OpErrorCode, message: string) =>
    new OpError(code, message, index, at.parent);
  const route = at.route ?? null;
  const position = at.index ?? null;

  const listSlot = LIST_SLOTS[kind];
  if (listSlot) {
    if (route !== null) throw refuse("invalid_placement", `${kind} '${at.parent}' has no routes`);
    const children = parent[listSlot] as unknown[];
    const where = position ?? children.length;
    if (where > children.length) {
      throw refuse(
        "invalid_placement",
        `${kind} '${at.parent}' has ${children.length} children; index ${where} is past the end`,
      );
    }
    children.splice(where, 0, node);
    return;
  }
  if (position !== null) {
    throw refuse("invalid_placement", `\`index\` is for sequences and parallels, not a ${kind}`);
  }
  if (kind === "loop" || kind === "map") {
    if (route !== null) throw refuse("invalid_placement", `${kind} '${at.parent}' has no routes`);
    if (parent.body != null) {
      throw refuse("slot_taken", `${kind} '${at.parent}' already has a body; remove it first`);
    }
    parent.body = node;
    return;
  }
  if (kind === "router") {
    if (route === null)
      throw refuse("invalid_placement", `give the \`route\` of router '${at.parent}'`);
    let holder: Json;
    let key: string;
    let label: string;
    if (route === DEFAULT_ROUTE) {
      [holder, key, label] = [parent, "default", "its default"];
    } else {
      const routes = Array.isArray(parent.routes) ? parent.routes.filter(isObject) : [];
      const found = routes.find((r) => r.id === route);
      if (!found)
        throw refuse("invalid_placement", `router '${at.parent}' has no route '${route}'`);
      [holder, key, label] = [found, "then", `route '${route}'`];
    }
    if (holder[key] != null) {
      throw refuse(
        "slot_taken",
        `router '${at.parent}' already has a node on ${label}; remove it first`,
      );
    }
    holder[key] = node;
    return;
  }
  throw refuse("invalid_placement", `${kind} '${at.parent}' holds no nodes`);
}

/** Remove `nodeId` from where it is, leaving an empty slot if it was a body or a route's
 * `then`; a removed `default` is simply gone. */
function takeOut(tree: Tree, nodeId: string, index: number): Json {
  const [node, place] = require(tree, nodeId, index);
  if (place.holder === tree.doc) {
    throw new OpError(
      "root_node",
      `'${nodeId}' is the workflow's root; it cannot be removed or moved`,
      index,
      nodeId,
    );
  }
  if (Array.isArray(place.holder)) place.holder.splice(place.key as number, 1);
  else if (place.holder === tree.pool || place.key === "default") {
    delete place.holder[place.key as string];
  } else place.holder[place.key as string] = null;
  return node;
}

function connect(tree: Tree, op: components["schemas"]["Connect"], index: number): void {
  if (op.to === op.from) {
    throw new OpError("invalid_move", `'${op.to}' cannot follow itself`, index, op.to);
  }
  const [to] = require(tree, op.to, index);
  require(tree, op.from, index);
  if (subtreeIds(to).includes(op.from)) {
    throw new OpError(
      "invalid_move",
      `'${op.from}' is inside '${op.to}', so '${op.to}' cannot follow it`,
      index,
      op.to,
    );
  }
  takeOut(tree, op.to, index);
  insertAfter(tree, op.from, to, op.sequence_id, index);
}

function disconnect(tree: Tree, op: components["schemas"]["Disconnect"], index: number): void {
  const [, fromPlace] = require(tree, op.from, index);
  const [, toPlace] = require(tree, op.to, index);
  if (
    fromPlace.slot !== "steps" ||
    toPlace.holder !== fromPlace.holder ||
    toPlace.key !== (fromPlace.key as number) + 1
  ) {
    throw new OpError(
      "not_connected",
      `'${op.to}' is not the step right after '${op.from}'`,
      index,
      op.to,
    );
  }
  tree.pool[op.to] = takeOut(tree, op.to, index);
}

const PATH_PART = /[A-Za-z_][A-Za-z0-9_]*|\[\d+\]/g;
const PATH_SHAPE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*$/;

function parsePath(path: string, index: number, nodeId: string | null): (string | number)[] {
  if (!PATH_SHAPE.test(path)) {
    throw new OpError(
      "invalid_path",
      `'${path}' is not a parameter path; use field names, \`.\` and \`[index]\`, e.g. \`routes[1].when\``,
      index,
      nodeId,
    );
  }
  return (path.match(PATH_PART) ?? []).map((p) => (p.startsWith("[") ? Number(p.slice(1, -1)) : p));
}

function isParam(kind: string, parts: (string | number)[]): boolean {
  const head = parts[0];
  if (head === "id" || head === "type" || NODE_SLOTS.has(String(head))) return false;
  if (kind === "router" && head === "routes") return parts.length >= 3 && parts[2] !== "then";
  return true;
}

function setParam(tree: Tree, op: components["schemas"]["SetParam"], index: number): void {
  const nodeId = op.node_id ?? null;
  const parts = parsePath(op.path, index, nodeId);
  let target: Json;
  let allowed: boolean;
  let what: string;
  if (nodeId === null) {
    target = tree.doc;
    allowed = DOCUMENT_PARAMS.has(String(parts[0]));
    what = "the document";
  } else {
    [target] = require(tree, nodeId, index);
    allowed = isParam(String(target.type), parts);
    what = `${String(target.type)} '${nodeId}'`;
  }
  if (!allowed) {
    throw new OpError(
      "not_a_param",
      `'${op.path}' is not a parameter of ${what}: ids, types and the nodes it holds change through addNode, removeNode, connect and disconnect`,
      index,
      nodeId,
    );
  }
  const badPath = (reason: string) =>
    new OpError("invalid_path", `'${op.path}' on ${what}: ${reason}`, index, nodeId);

  let container: unknown = target;
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i];
    if (typeof part === "number") {
      if (!Array.isArray(container) || part >= container.length) {
        throw badPath(`there is no item ${part}`);
      }
      container = container[part];
      continue;
    }
    if (!isObject(container)) throw badPath(`'${part}' is not inside an object`);
    if (container[part] == null) container[part] = typeof parts[i + 1] === "number" ? [] : {};
    container = container[part];
  }
  const last = parts[parts.length - 1];
  if (typeof last === "number") {
    if (!Array.isArray(container) || last >= container.length) {
      throw badPath(`there is no item ${last}`);
    }
    if (op.value === null) throw badPath("an item cannot be unset; set the whole list");
    container[last] = op.value;
  } else if (!isObject(container)) {
    throw badPath(`'${last}' is not inside an object`);
  } else if (op.value === null) {
    delete container[last];
  } else {
    container[last] = structuredClone(op.value);
  }
}

function missing(node: Json, what: string): never {
  throw new OpError(
    "missing_child",
    `${String(node.type)} '${String(node.id)}' ${what}; add a node there`,
    null,
    typeof node.id === "string" ? node.id : null,
  );
}

function checkResult(tree: Tree): void {
  const [detached] = Object.values(tree.pool);
  if (isObject(detached)) {
    const nodeId = String(detached.id);
    throw new OpError(
      "detached_nodes",
      `'${nodeId}' is not placed in the workflow; connect it or remove it`,
      null,
      nodeId,
    );
  }
  for (const [node] of tree.places()) {
    if ((node.type === "loop" || node.type === "map") && node.body == null) {
      missing(node, "has no body");
    }
    if (node.type === "router" && Array.isArray(node.routes)) {
      for (const route of node.routes) {
        if (isObject(route) && route.then == null) {
          missing(node, `has nothing on route '${String(route.id)}'`);
        }
      }
    }
  }
}
