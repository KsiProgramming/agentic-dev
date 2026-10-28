import type { components } from "@/api/schema";

type SpecNode = components["schemas"]["WorkflowSpec"]["root"];

/**
 * Where a node runs, from the run's spec: in a branch of a parallel, an item of a map, an
 * iteration of a loop or the route of a router. Node ids are unique in a spec, so this places a
 * node's events exactly, where the events' `item` and `branch` tags alone are ambiguous (two
 * nested parallels, or two routers, running at once).
 */
export interface SpecParent {
  /** The id of the loop, map, parallel or router the node is directly in. */
  container: string;
  kind: "loop" | "map" | "parallel" | "router";
  /** For a parallel: the index of the branch the node is in. */
  branch: number | null;
}

/** Each node's container, by node id; nodes at the top of the run are left out. */
export function specParents(root: SpecNode): Map<string, SpecParent> {
  const parents = new Map<string, SpecParent>();
  const visit = (node: SpecNode, parent: SpecParent | null) => {
    if (parent) parents.set(node.id, parent);
    switch (node.type) {
      case "sequence":
        for (const step of node.steps) visit(step, parent);
        break;
      case "loop":
      case "map":
        visit(node.body, { container: node.id, kind: node.type, branch: null });
        break;
      case "parallel":
        node.branches.forEach((branch, index) =>
          visit(branch, { container: node.id, kind: "parallel", branch: index }),
        );
        break;
      case "router": {
        const inRoute: SpecParent = { container: node.id, kind: "router", branch: null };
        for (const route of node.routes) visit(route.then, inRoute);
        if (node.default) visit(node.default, inRoute);
        break;
      }
      default:
        break;
    }
  };
  visit(root, null);
  return parents;
}
