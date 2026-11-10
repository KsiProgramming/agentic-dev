import { routesOf, type SpecNode, type WorkflowSpec } from "@/runs/graph/spec-graph";

/**
 * The builder's mirror of the engine's port check (4.2, `port_issues` in
 * `agentic_engine/spec/models.py`), so the canvas refuses a connection whose ports do not fit
 * before it is made (5.6). `schemas/fixtures/port-checks.json` keeps the two alike. Only the
 * `port_mismatch` half is mirrored; whether a schema is valid JSON Schema stays the server's
 * check (`invalid_schema`), and a schema that is plainly not a port's is skipped here as there.
 */

type Json = Record<string, unknown>;
type PortNode = Extract<SpecNode, { type: "agent" | "tool" }>;
type ReduceNode = Extract<SpecNode, { type: "reduce" }>;
/** A node whose output may be typed: a port node, or a reduce that merges findings. */
type Producer = PortNode | ReduceNode;

/** An incompatible connection: `consumer` cannot take what `producer` gives. For a merged
 * source, `consumer` is the source and `producer` the reduce merging it. */
export interface Mismatch {
  producer: string;
  consumer: string;
  /** As the engine's issue says it. */
  message: string;
  /** The same, as a sentence naming the consumer, for a disabled menu item. */
  reason: string;
}

/** The top-level property types of the findings report (`schemas/findings.v1.json`), the output
 * of a `dedupe` or `vote` reduce; a property with no `type` (a `$ref`, an `anyOf`) has none. */
export const FINDINGS_PROPERTIES: Record<string, string[]> = {
  checks: ["array"],
  counts: ["object"],
  db_as_of: [],
  findings: ["array"],
  scanner: [],
  sources: [],
  truncated: ["boolean"],
};

const FINDINGS_SCHEMA: Json = {
  type: "object",
  properties: Object.fromEntries(
    Object.entries(FINDINGS_PROPERTIES).map(([name, types]) => [
      name,
      types.length ? { type: types } : {},
    ]),
  ),
};

const MAX_SCHEMA_BYTES = 16 * 1024;
const DIALECT = "https://json-schema.org/draft/2020-12/schema";

const isPort = (node: SpecNode): node is PortNode => node.type === "agent" || node.type === "tool";
const merges = (node: SpecNode): node is ReduceNode =>
  node.type === "reduce" && (node.strategy === "dedupe" || node.strategy === "vote");

function outputSchema(node: Producer): Json | null {
  if (node.type === "reduce") return merges(node) ? FINDINGS_SCHEMA : null;
  return (node.output_schema as Json | null | undefined) ?? null;
}

function* refs(value: unknown): Generator<string> {
  if (Array.isArray(value)) for (const item of value) yield* refs(item);
  else if (value && typeof value === "object") {
    for (const [key, inner] of Object.entries(value)) {
      if (key === "$ref" && typeof inner === "string") yield inner;
      else yield* refs(inner);
    }
  }
}

/** Whether `schema` plainly cannot be a port's (the engine reports it as `invalid_schema` and
 * draws no edge from or to its node). */
function broken(schema: Json): boolean {
  if (JSON.stringify(schema).length > MAX_SCHEMA_BYTES) return true;
  if (schema.$schema !== undefined && schema.$schema !== DIALECT) return true;
  if (schema.type !== "object") return true;
  for (const ref of refs(schema)) if (!ref.startsWith("#")) return true;
  return false;
}

function properties(schema: Json): Json {
  const p = schema.properties;
  return p && typeof p === "object" && !Array.isArray(p) ? (p as Json) : {};
}

/** A property schema's top-level `type`s; empty when it does not say. */
function types(schema: unknown): Set<string> {
  if (!schema || typeof schema !== "object") return new Set();
  const t = (schema as Json).type;
  if (typeof t === "string") return new Set([t]);
  if (Array.isArray(t)) return new Set(t.filter((x): x is string => typeof x === "string"));
  return new Set();
}

const either = (set: Set<string>) => [...set].sort().join(" or ");

/** Why `wanted` cannot take what `out` gives, as the engine's `_port_mismatch` words it. */
function portMismatch(out: Json, wanted: Json, producer: string): string | null {
  const given = properties(out);
  const expected = properties(wanted);
  const required = Array.isArray(wanted.required) ? wanted.required : [];
  for (const name of required) {
    if (typeof name !== "string") continue;
    if (!(name in given)) {
      return `requires '${name}', which the output_schema of '${producer}' does not declare`;
    }
    const has = types(given[name]);
    const needs = types(expected[name]);
    if (needs.has("number")) needs.add("integer");
    if (has.size && needs.size && ![...has].some((t) => needs.has(t))) {
      return `wants '${name}' as ${either(needs)}, but the output_schema of '${producer}' gives ${either(has)}`;
    }
  }
  return null;
}

function equal(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => equal((a as Json)[k], (b as Json)[k]));
}

/** A writer whose type cannot be told (a router's routes write the name with different types):
 * no edge is drawn from it. */
const UNTYPED = { type: "reduce", id: "untyped", from: "untyped", strategy: "concat" } as Producer;

type Seen = Map<string, Producer>;

/** For each node that reads run artifacts, the node that last wrote each one before it, as the
 * engine's `_walk_artifacts` finds them (its issues are the server's). */
function artifactWriters(root: SpecNode): Map<string, Seen> {
  const writers = new Map<string, Seen>();
  const visit = (node: SpecNode, seen: Seen): Seen => {
    switch (node.type) {
      case "agent":
      case "tool": {
        const reads = node.reads ?? [];
        if (reads.length) {
          writers.set(
            node.id,
            new Map(reads.filter((n) => seen.has(n)).map((n) => [n, seen.get(n)!])),
          );
        }
        return node.writes ? new Map([...seen, [node.writes, node]]) : seen;
      }
      case "reduce":
        return node.writes ? new Map([...seen, [node.writes, node]]) : seen;
      case "sequence":
        for (const step of node.steps) seen = visit(step, seen);
        return seen;
      case "loop":
        return visit(node.body, seen);
      case "map":
        visit(node.body, seen);
        return seen;
      case "orchestrator":
        // Its worker runs once per task; its output, stored by its own `writes`, is untyped.
        visit(node.body, seen);
        return node.writes ? new Map([...seen, [node.writes, UNTYPED]]) : seen;
      case "parallel": {
        const after = new Map(seen);
        const written = new Set<string>();
        for (const branch of node.branches) {
          for (const [name, writer] of visit(branch, seen)) {
            if (seen.get(name) === writer || written.has(name)) continue;
            written.add(name);
            after.set(name, writer);
          }
        }
        return after;
      }
      case "router": {
        const wrote = routesOf(node).map(([, route]) => visit(route, seen));
        const after = new Map(seen);
        for (const [name, writer] of wrote[0] ?? []) {
          const all = wrote.map((w) => w.get(name));
          if (seen.get(name) === writer || all.some((w) => w === undefined)) continue;
          const alike = all.every((w) => equal(outputSchema(w!), outputSchema(writer)));
          after.set(name, alike ? writer : UNTYPED);
        }
        return after;
      }
      default:
        return seen;
    }
  };
  visit(root, new Map());
  return writers;
}

/** Each place where one node's output is the next agent or tool node's input, as the engine's
 * `port_edges` finds them: consecutive steps (nested sequences flattened, gates looked through),
 * or an artifact's last writer for a node that reads one. */
function portEdges(root: SpecNode): [Producer, PortNode][] {
  const edges: [Producer, PortNode][] = [];
  const writers = artifactWriters(root);
  const steps = function* (node: SpecNode): Generator<SpecNode> {
    if (node.type === "sequence") for (const step of node.steps) yield* steps(step);
    else yield node;
  };
  const visit = (node: SpecNode) => {
    let previous: Producer | null = null;
    for (const step of steps(node)) {
      switch (step.type) {
        case "agent":
        case "tool": {
          const reads = step.reads ?? [];
          if (reads.length) {
            const source = reads.length === 1 ? writers.get(step.id)?.get(reads[0]) : undefined;
            if (source && (isPort(source) || merges(source))) edges.push([source, step]);
          } else if (previous) {
            edges.push([previous, step]);
          }
          previous = step;
          break;
        }
        case "gate":
          // A selection gate passes on the chosen items, not its input (6.7).
          if (step.select) previous = null;
          break;
        case "loop":
        case "map":
        case "orchestrator":
          previous = null;
          visit(step.body);
          break;
        case "parallel":
          previous = null;
          for (const branch of step.branches) visit(branch);
          break;
        case "router":
          previous = null;
          for (const [, route] of routesOf(step)) visit(route);
          break;
        case "reduce":
          previous = merges(step) ? step : null;
          break;
        default:
          previous = null;
      }
    }
  };
  visit(root);
  return edges;
}

/** The agent or tool node whose output is `node`'s output, if there is one. */
function lastStep(node: SpecNode): PortNode | null {
  if (isPort(node)) return node;
  if (node.type !== "sequence") return null;
  const last = [...node.steps].reverse().find((s) => s.type !== "gate");
  return last ? lastStep(last) : null;
}

/** Each node a `dedupe` or `vote` reduce merges, with the reduce: the last step of a map's or
 * orchestrator's body or of each parallel branch. */
function mergeSources(nodes: SpecNode[]): [ReduceNode, PortNode][] {
  const containers = new Map<string, SpecNode>();
  const found: [ReduceNode, PortNode][] = [];
  for (const node of nodes) {
    if (node.type === "map" || node.type === "parallel" || node.type === "orchestrator") {
      containers.set(node.id, node);
    } else if (merges(node) && containers.has(node.from)) {
      const source = containers.get(node.from)!;
      const outputs =
        source.type === "map" || source.type === "orchestrator"
          ? [source.body]
          : source.type === "parallel"
            ? source.branches
            : [];
      for (const out of outputs) {
        const last = lastStep(out);
        if (last) found.push([node, last]);
      }
    }
  }
  return found;
}

function* depthFirst(node: SpecNode): Generator<SpecNode> {
  yield node;
  if (node.type === "sequence") for (const step of node.steps) yield* depthFirst(step);
  if (node.type === "loop" || node.type === "map" || node.type === "orchestrator") {
    yield* depthFirst(node.body);
  }
  if (node.type === "parallel") for (const branch of node.branches) yield* depthFirst(branch);
  if (node.type === "router") for (const [, route] of routesOf(node)) yield* depthFirst(route);
}

/** The incompatible connections in `spec`, in run order of the node each is on. */
export function portMismatches(spec: WorkflowSpec): Mismatch[] {
  const nodes = [...depthFirst(spec.root)];
  const brokenIds = new Set(
    nodes
      .filter(isPort)
      .filter((n) => [n.input_schema, n.output_schema].some((s) => s != null && broken(s as Json)))
      .map((n) => n.id),
  );
  const found: Mismatch[] = [];
  for (const [producer, consumer] of portEdges(spec.root)) {
    const out = outputSchema(producer);
    const wanted = (consumer.input_schema as Json | null | undefined) ?? null;
    if (!out || !wanted || brokenIds.has(producer.id) || brokenIds.has(consumer.id)) continue;
    const why = portMismatch(out, wanted, producer.id);
    if (why) {
      found.push({
        producer: producer.id,
        consumer: consumer.id,
        message: `${consumer.type} '${consumer.id}': input_schema ${why}`,
        reason: `The input_schema of '${consumer.id}' ${why}.`,
      });
    }
  }
  for (const [reduce, source] of mergeSources(nodes)) {
    const out = (source.output_schema as Json | null | undefined) ?? null;
    if (!out || brokenIds.has(source.id)) continue;
    const findings = properties(out).findings;
    const t = types(findings);
    if (findings === undefined || (t.size && !t.has("array"))) {
      found.push({
        producer: reduce.id,
        consumer: source.id,
        message: `${source.type} '${source.id}': reduce '${reduce.id}' merges its output as a findings report, but its output_schema has no \`findings\` array`,
        reason: `'${reduce.id}' merges the output of '${source.id}' as findings, but its output_schema has no \`findings\` array.`,
      });
    }
  }
  const order = new Map(nodes.map((n, i) => [n.id, i]));
  return found.sort((a, b) => order.get(a.consumer)! - order.get(b.consumer)!);
}
