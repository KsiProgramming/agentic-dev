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
  | components["schemas"]["SetParam"]
  | components["schemas"]["Wrap"]
  | components["schemas"]["Extract"];
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
const DOCUMENT_PARAMS = new Set([
  "name",
  "description",
  "budget_usd",
  "input",
  "input_schema",
  "output_schema",
]);
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
  return applyGraphOps(spec, ops).spec;
}

/** What a batch makes: the spec, and the workflow an `extract` moved nodes into (6.6), which the
 * server stores as that workflow's version 1 (`null` without one). */
export interface AppliedOps<S> {
  spec: S;
  extracted: Json | null;
}

/** As `applyOps`, with the workflow an `extract` made. */
export function applyGraphOps<S>(spec: S, ops: readonly GraphOp[]): AppliedOps<S> {
  const tree = new Tree(spec);
  let extracted: Json | null = null;
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
      case "wrap":
        return wrap(tree, op, index);
      case "extract":
        if (extracted !== null) {
          throw new OpError(
            "invalid_extract",
            "a batch may hold one extract; save, then extract again",
            index,
            op.node_ids[0] ?? null,
          );
        }
        extracted = extract(tree, op, index);
        return;
    }
  });
  checkResult(tree);
  return { spec: tree.doc as S, extracted };
}

/** The containers `wrap` may put nodes in (6.6). */
export const WRAP_KINDS = ["sequence", "parallel", "loop", "map"] as const;

/** The nodes `nodeIds` name, in run order, with the place of the first: one node anywhere (but
 * detached), or consecutive steps of one sequence. */
function selection(
  tree: Tree,
  nodeIds: readonly string[],
  index: number,
  code: OpErrorCode,
): [Place, Json[]] {
  const refuse = (message: string, nodeId: string) => new OpError(code, message, index, nodeId);
  const repeated = nodeIds.find((id, i) => nodeIds.indexOf(id) !== i);
  if (repeated !== undefined) throw refuse(`'${repeated}' is named twice`, repeated);
  const found = nodeIds.map((id) => require(tree, id, index));
  const detached = new Set(
    Object.values(tree.pool)
      .filter(isObject)
      .flatMap((node) => subtreeIds(node)),
  );
  for (const id of nodeIds) {
    if (detached.has(id)) throw refuse(`'${id}' is not placed in the workflow`, id);
  }
  if (found.length === 1) {
    const [node, place] = found[0];
    return [place, [node]];
  }
  const holder = found[0][1].holder;
  found.forEach(([, place], i) => {
    if (place.slot !== "steps" || place.holder !== holder) {
      throw refuse(
        `'${nodeIds[i]}' is not a step of the same sequence as '${nodeIds[0]}'; pick one node, or consecutive steps of one sequence`,
        nodeIds[i],
      );
    }
  });
  const ordered = [...found].sort((a, b) => (a[1].key as number) - (b[1].key as number));
  const keys = ordered.map(([, place]) => place.key as number);
  for (let i = 1; i < keys.length; i++) {
    if (keys[i] !== keys[i - 1] + 1) {
      const gap = (holder as unknown[])[keys[i - 1] + 1] as Json;
      throw refuse(
        `the steps are not consecutive: '${String(gap.id)}' is between them`,
        String(gap.id),
      );
    }
  }
  return [ordered[0][1], ordered.map(([node]) => node)];
}

/** Put `value` where the `count` nodes from `place` on are. */
function replace(place: Place, count: number, value: Json): void {
  if (count === 1) setAt(place, value);
  else (place.holder as unknown[]).splice(place.key as number, count, value);
}

function wrap(tree: Tree, op: components["schemas"]["Wrap"], index: number): void {
  const [place, nodes] = selection(tree, op.node_ids, index, "invalid_wrap");
  const first = op.node_ids[0];
  const refuse = (message: string) => new OpError("invalid_wrap", message, index, first);
  const container = structuredClone(op.with) as Json;
  const kind = container.type;
  const containerId = container.id;
  if (!(WRAP_KINDS as readonly unknown[]).includes(kind)) {
    throw refuse("wrap puts nodes in a sequence, parallel, loop or map");
  }
  if (typeof containerId !== "string") throw refuse(`give the new ${String(kind)} an \`id\``);
  const held = Object.keys(container)
    .filter((key) => NODE_SLOTS.has(key))
    .sort();
  if (held.length > 0) {
    throw refuse(`\`with\` holds no nodes (${held.join(", ")}); they are the wrapped ones`);
  }
  if (tree.ids().has(containerId)) throw duplicate(containerId, index);
  if (kind === "sequence") container.steps = nodes;
  else if (kind === "parallel") {
    if (nodes.length < 2) {
      throw refuse("a parallel needs two or more branches; wrap two or more steps");
    }
    container.branches = nodes;
  } else if (nodes.length === 1) container.body = nodes[0];
  else {
    const sequenceId = op.sequence_id ?? null;
    if (sequenceId === null) {
      throw refuse(`give \`sequence_id\`: the ${kind}'s body holds the steps in a sequence`);
    }
    if (sequenceId === containerId)
      throw refuse(`\`sequence_id\` and the ${kind}'s id must differ`);
    if (tree.ids().has(sequenceId)) throw duplicate(sequenceId, index);
    container.body = { type: "sequence", id: sequenceId, steps: nodes };
  }
  replace(place, nodes.length, container);
}

const RESULTS = /\bresults\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*["']([^"']+)["']\s*\])/g;

/** The node ids `node` itself refers to: a reduce's `from`, a publisher's `from_node` and the
 * results its expressions read. */
function references(node: Json): Set<string> {
  const found = new Set<string>();
  if (node.type === "reduce" && typeof node.from === "string") found.add(node.from);
  if (isObject(node.args) && typeof node.args.from_node === "string") {
    found.add(node.args.from_node);
  }
  const expressions: unknown[] = [node.until, node.over];
  if (node.type === "subflow") expressions.push(node.input);
  if (node.type === "router" && Array.isArray(node.routes)) {
    for (const route of node.routes) if (isObject(route)) expressions.push(route.when);
  }
  for (const expression of expressions) {
    if (typeof expression !== "string") continue;
    for (const match of expression.matchAll(RESULTS)) found.add(match[1] ?? match[2]);
  }
  return found;
}

/** The orchestrator whose worker holds `nodeId`, if one does. */
function inWorker(tree: Tree, nodeId: string): string | null {
  for (const [node] of tree.places()) {
    if (
      node.type === "orchestrator" &&
      isObject(node.body) &&
      subtreeIds(node.body).includes(nodeId)
    ) {
      return String(node.id);
    }
  }
  return null;
}

/** The `side` schema of the agent or tool node whose port is `node`'s. */
function portOf(node: Json, side: "input" | "output"): unknown {
  if (node.type === "agent" || node.type === "tool") return node[`${side}_schema`];
  if (node.type !== "sequence" || !Array.isArray(node.steps)) return undefined;
  const steps = node.steps.filter((s): s is Json => isObject(s) && s.type !== "gate");
  if (steps.length === 0) return undefined;
  return portOf(side === "input" ? steps[0] : steps[steps.length - 1], side);
}

function extract(tree: Tree, op: components["schemas"]["Extract"], index: number): Json {
  const [place, nodes] = selection(tree, op.node_ids, index, "invalid_extract");
  const first = op.node_ids[0];
  const refuse = (message: string, nodeId: string = first) =>
    new OpError("invalid_extract", message, index, nodeId);
  if (place.holder === tree.doc) {
    throw new OpError(
      "root_node",
      `'${first}' is the workflow's root; extract steps of it instead`,
      index,
      first,
    );
  }
  if (op.workflow.id === tree.doc.id) {
    throw refuse(`the new workflow needs an id of its own, not '${op.workflow.id}'`);
  }
  const hub = inWorker(tree, first);
  if (hub !== null) {
    throw refuse(`'${first}' is in the worker of orchestrator '${hub}', which runs no subflow`);
  }
  const inside = new Set(nodes.flatMap((node) => subtreeIds(node)));
  for (const node of nodes) {
    for (const [inner] of walk(node, { holder: {}, key: "", parent: null, slot: null })) {
      for (const ref of references(inner)) {
        if (!inside.has(ref)) {
          throw refuse(
            `'${String(inner.id)}' refers to '${ref}', which stays outside; extract them together, or change the reference first`,
            String(inner.id),
          );
        }
      }
    }
  }
  for (const [outer] of tree.places()) {
    if (inside.has(String(outer.id))) continue;
    for (const ref of references(outer)) {
      if (inside.has(ref)) {
        throw refuse(
          `'${String(outer.id)}' refers to '${ref}', which would move into the new workflow; extract them together, or change the reference first`,
          String(outer.id),
        );
      }
    }
  }
  if (tree.ids().has(op.subflow_id) && !inside.has(op.subflow_id)) {
    throw duplicate(op.subflow_id, index);
  }
  let root: Json;
  if (nodes.length === 1) root = nodes[0];
  else {
    let rootId = "main";
    for (let n = 2; inside.has(rootId); n++) rootId = `main_${n}`;
    root = { type: "sequence", id: rootId, steps: nodes };
  }
  const document: Json = { spec_version: "0", id: op.workflow.id, name: op.workflow.name };
  if (op.workflow.description) document.description = op.workflow.description;
  const input = portOf(nodes[0], "input");
  if (input != null) document.input_schema = input;
  const output = portOf(nodes[nodes.length - 1], "output");
  if (output != null) document.output_schema = output;
  document.root = root;
  replace(place, nodes.length, {
    type: "subflow",
    id: op.subflow_id,
    workflow: { id: op.workflow.id, version: 1 },
  });
  return structuredClone(document);
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
  if (kind === "loop" || kind === "map" || kind === "orchestrator") {
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
    if (
      (node.type === "loop" || node.type === "map" || node.type === "orchestrator") &&
      node.body == null
    ) {
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
