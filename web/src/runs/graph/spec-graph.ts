import type { components } from "@/api/schema";

import { calledRoot } from "../calls";

/**
 * The run's workflow spec as the console reads it: its node types, what each node does in one
 * line, a router's routes and every node in run order. The Graph tab draws it as a map
 * (`run-map.tsx`); the step list, input and usage tabs look nodes up here.
 */

export type WorkflowSpec = components["schemas"]["WorkflowSpec"];
export type SpecNode = WorkflowSpec["root"];
export type NodeKind = SpecNode["type"];

type RouterSpec = Extract<SpecNode, { type: "router" }>;

export const DEFAULT_ROUTE = "default";

/** The id of route `routeId` of router `routerId`, as the map and the node states key it. Spec
 * node ids have no `:`, so it never clashes with one. */
export function routeNodeId(routerId: string, routeId: string): string {
  return `${routerId}:route:${routeId}`;
}

const REDUCE_LABEL: Record<Extract<SpecNode, { type: "reduce" }>["strategy"], string> = {
  agent: "Agent",
  concat: "Concat",
  dedupe: "Dedupe",
  vote: "Vote",
};

/** One line on what a node does: an agent's role, a tool's name, a gate's title. */
export function nodeDetail(node: SpecNode): string {
  switch (node.type) {
    case "agent":
      return node.role;
    case "tool":
      return node.tool;
    case "gate":
      return node.title;
    case "reduce":
      return `${REDUCE_LABEL[node.strategy]} of ${node.from}`;
    case "loop":
      return `Up to ${node.max_iterations} iterations`;
    case "map":
      return `Each item, ${node.max_concurrency} at a time`;
    case "parallel": {
      const n = node.branches.length;
      if (node.join === "all") return `All ${n} branches`;
      if (node.join === "any") return `Any of ${n} branches`;
      return `${node.quorum ?? n} of ${n} branches`;
    }
    case "router": {
      const n = routesOf(node).length;
      const by = node.classifier ? "a classifier" : "rules";
      return `One of ${n} ${n === 1 ? "route" : "routes"}, by ${by}`;
    }
    case "orchestrator":
      return `Up to ${node.max_workers} tasks, ${node.max_concurrency} at a time`;
    case "subflow":
      return `Calls ${node.workflow.id} · version ${node.workflow.version}`;
    case "sequence":
      return "";
    default:
      // A kind the engine added after this app was built (5.3): its card shows its kind.
      return "";
  }
}

/** A router's routes as `[route id, what runs on it]`, `default` last. */
export function routesOf(router: RouterSpec): [string, SpecNode][] {
  const routes: [string, SpecNode][] = router.routes.map((r) => [r.id, r.then]);
  if (router.default) routes.push([DEFAULT_ROUTE, router.default]);
  return routes;
}

function* specNodes(node: SpecNode): Generator<SpecNode> {
  yield node;
  if (node.type === "sequence") for (const step of node.steps) yield* specNodes(step);
  if (node.type === "loop" || node.type === "map" || node.type === "orchestrator") {
    yield* specNodes(node.body);
  }
  if (node.type === "parallel") for (const branch of node.branches) yield* specNodes(branch);
  if (node.type === "router") for (const [, route] of routesOf(node)) yield* specNodes(route);
  const called = calledRoot(node);
  if (called) yield* specNodes(called);
}

/** Every node of the spec, depth first in run order, sequences included. */
export function allSpecNodes(spec: WorkflowSpec): SpecNode[] {
  return [...specNodes(spec.root)];
}
