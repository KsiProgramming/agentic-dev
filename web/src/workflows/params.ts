import type { SpecNode, WorkflowSpec } from "@/runs/graph/spec-graph";

import type { Edit } from "./edits";
import type { NodeManifest } from "./node-types";
import type { GraphOp } from "./ops";

/**
 * The side panel's values (5.4): a node's parameters as its manifest's form shows them, and the
 * `setParam` ops that turn one set of values into another. Pure, so the panel and its tests share
 * it.
 */

type Json = Record<string, unknown>;

/** A JSON Schema as a manifest's `parameters` holds it. */
export type Schema = Json;

/** The workflow's own fields, as `setParam` without a node sets them. */
export const DOCUMENT_FIELDS = [
  "name",
  "description",
  "budget_usd",
  "input",
  "input_schema",
  "output_schema",
] as const;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** `node`'s parameters: every field but `type`, `id` and the slots that hold nodes
 * (`routes[].then` drops each route's `then`). */
export function nodeParams(node: SpecNode, manifest: NodeManifest | undefined): Json {
  const slots = manifest?.slots ?? [];
  const values: Json = {};
  for (const [key, value] of Object.entries(node as unknown as Json)) {
    if (key === "type" || key === "id" || slots.includes(key)) continue;
    const listSlot = slots.find((s) => s.startsWith(`${key}[].`));
    if (listSlot && Array.isArray(value)) {
      const field = listSlot.slice(key.length + 3);
      values[key] = value.map((item) => {
        if (!isObject(item)) return item;
        return Object.fromEntries(Object.entries(item).filter(([k]) => k !== field));
      });
    } else {
      values[key] = value;
    }
  }
  return values;
}

/** The workflow's name, description and budget. */
export function documentParams(spec: WorkflowSpec): Json {
  const doc = spec as unknown as Json;
  return Object.fromEntries(DOCUMENT_FIELDS.filter((f) => f in doc).map((f) => [f, doc[f]]));
}

/** `schema` with a local `$ref` (`#/$defs/Route`) resolved against `root`; its own keys win. */
export function resolveSchema(schema: Schema | undefined, root: Schema): Schema {
  const ref = schema?.$ref;
  if (typeof ref !== "string" || !ref.startsWith("#/")) return schema ?? {};
  let target: unknown = root;
  for (const part of ref.slice(2).split("/")) target = isObject(target) ? target[part] : undefined;
  const rest = Object.entries(schema as Json).filter(([k]) => k !== "$ref");
  return { ...(isObject(target) ? target : {}), ...Object.fromEntries(rest) };
}

/** A value as the spec keeps it: an empty string, an empty object and `undefined` are unset.
 * `sorted` orders object keys, to compare values a form rebuilt in its schema's order. */
function normalise(value: unknown, sorted = false): unknown {
  if (value === undefined || value === "") return undefined;
  if (Array.isArray(value)) return value.map((v) => normalise(v, sorted));
  if (isObject(value)) {
    const entries = Object.entries(value);
    if (sorted) entries.sort(([a], [b]) => a.localeCompare(b));
    const out: Json = {};
    for (const [k, v] of entries) {
      const n = normalise(v, sorted);
      if (n !== undefined) out[k] = n;
    }
    return Object.keys(out).length > 0 ? out : undefined;
  }
  return value;
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(normalise(a, true)) === JSON.stringify(normalise(b, true));
}

/** Whether two sets of values are the same once unset fields are left out. */
export function sameParams(a: Json, b: Json): boolean {
  return same(a, b);
}

/** Fields of an object the form edits one by one; one without `properties` (a port schema, a
 * tool's `args`) is a value set whole. */
function properties(schema: Schema): Json | null {
  return isObject(schema.properties) ? schema.properties : null;
}

/**
 * The `setParam` ops that change `before` into `after` for node `nodeId` (`null`: the document),
 * at leaf paths: a scalar or a list of scalars is set whole (`tools`), an object with fields is
 * entered (`classifier.instructions`), a list of objects is set per item field (`routes[1].when`),
 * and an object that was unset is set whole. A field cleared is set to `null`. No op when nothing
 * changed.
 */
export function paramOps(
  nodeId: string | null,
  before: Json,
  after: Json,
  schema: Schema,
): GraphOp[] {
  const ops: GraphOp[] = [];
  const set = (path: string, value: unknown) => {
    const op = { op: "setParam" as const, path, value: (normalise(value) ?? null) as never };
    ops.push(nodeId === null ? op : { ...op, node_id: nodeId });
  };

  function diff(path: string, a: unknown, b: unknown, at: Schema) {
    if (same(a, b)) return;
    const resolved = resolveSchema(at, schema);
    const fields = properties(resolved);
    if (fields && isObject(a) && isObject(b)) {
      for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
        diff(path ? `${path}.${key}` : key, a[key], b[key], (fields[key] as Schema) ?? {});
      }
      return;
    }
    const items = resolveSchema(resolved.items as Schema | undefined, schema);
    if (Array.isArray(a) && Array.isArray(b) && a.length === b.length && properties(items)) {
      b.forEach((item, i) => diff(`${path}[${i}]`, a[i], item, items));
      return;
    }
    set(path, b);
  }

  diff("", before, after, schema);
  return ops;
}

/**
 * The edit that sets these fields, or `null` when nothing changed. Its `key` names the node and
 * paths, so the builder keeps typing in one field as one undo step.
 */
export function paramEdit(
  nodeId: string | null,
  before: Json,
  after: Json,
  schema: Schema,
): Edit | null {
  const ops = paramOps(nodeId, before, after, schema);
  if (ops.length === 0) return null;
  const paths = ops.map((op) => (op.op === "setParam" ? op.path : "")).join(", ");
  const label = nodeId === null ? `Change the workflow's ${paths}` : `Change ${paths} of ${nodeId}`;
  return { label, ops, key: `${nodeId ?? ""}:${paths}` };
}
