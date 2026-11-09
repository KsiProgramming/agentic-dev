import type { components } from "@/api/schema";

import type { SpecNode, WorkflowSpec } from "./graph/spec-graph";

/** A `subflow` of a run as `GET /runs/{id}` gives it (6.5): the workflow it calls, that
 * workflow's root as it ran (its nodes under the ids they ran as) and which ids were renamed. */
export type RunCall = components["schemas"]["RunCall"];

type SubflowSpec = Extract<SpecNode, { type: "subflow" }>;

/** A subflow with the root it called attached: what the console reads instead of a leaf. */
type CalledSubflow = SubflowSpec & { call?: SpecNode };

/**
 * The run's spec with each subflow's called root attached (`calledRoot`), from the run's `calls`,
 * a subflow inside a called root too. Without calls the spec is returned as it is. The spec is
 * copied, never changed: the query cache keeps the API's answer.
 */
export function withCalls(
  spec: WorkflowSpec,
  calls: Record<string, RunCall> | null | undefined,
): WorkflowSpec {
  if (!calls || Object.keys(calls).length === 0) return spec;
  const attach = (node: SpecNode, depth: number): SpecNode => {
    switch (node.type) {
      case "subflow": {
        const found = calls[node.id];
        // A call can hold itself only through a cycle the engine refuses; stop all the same.
        if (!found || depth > 8) return node;
        const call = attach(found.root as unknown as SpecNode, depth + 1);
        return { ...node, call } as CalledSubflow;
      }
      case "sequence":
        return { ...node, steps: node.steps.map((s) => attach(s, depth)) };
      case "loop":
      case "map":
      case "orchestrator":
        return { ...node, body: attach(node.body, depth) };
      case "parallel":
        return { ...node, branches: node.branches.map((b) => attach(b, depth)) };
      case "router":
        return {
          ...node,
          routes: node.routes.map((r) => ({ ...r, then: attach(r.then, depth) })),
          default: node.default ? attach(node.default, depth) : node.default,
        };
      default:
        return node;
    }
  };
  return { ...spec, root: attach(spec.root, 0) };
}

/** The root a subflow called in this run, once `withCalls` attached it; `null` for any other
 * node, and in the builder, where a subflow is a leaf. */
export function calledRoot(node: SpecNode): SpecNode | null {
  return node.type === "subflow" ? ((node as CalledSubflow).call ?? null) : null;
}
