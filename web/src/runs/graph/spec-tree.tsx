import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { calledRoot } from "../calls";

import {
  nodeDetail,
  routeNodeId,
  routesOf,
  type NodeKind,
  type SpecNode,
  type WorkflowSpec,
} from "./spec-graph";

/**
 * A workflow spec drawn as chains of cards (design-language.md → Components → Run map): the steps
 * top to bottom in run order, a container's body, branches or routes hanging off it to the right.
 * The run map (statuses) and the builder (edit menus) draw their own cards in it (5.2).
 */

/** One card of the map: a spec node, or a router's route; its children hang off it. */
export interface MapNode {
  id: string;
  name: string;
  kind: NodeKind | "route";
  detail: string;
  /** A container's body, branches or routes, each a chain of its own. */
  children: MapNode[][];
}

/** The spec as chains of cards: a sequence is its steps one under the other; a container's
 * body, each branch and each route is a chain hanging off it to the right. */
function chain(node: SpecNode): MapNode[] {
  if (node.type === "sequence") return node.steps.flatMap(chain);
  let children: MapNode[][] = [];
  if (node.type === "loop" || node.type === "map" || node.type === "orchestrator") {
    children = [chain(node.body)];
  }
  if (node.type === "parallel") children = node.branches.map(chain);
  // In a run, the workflow a subflow called hangs off it like a body (6.5); in the builder a
  // subflow is a leaf: the workflow it calls is edited on its own page.
  const called = calledRoot(node);
  if (called) children = [chain(called)];
  if (node.type === "router") {
    children = routesOf(node).map(([routeId, route]) => [
      {
        id: routeNodeId(node.id, routeId),
        name: routeId,
        kind: "route" as const,
        detail: "Route",
        children: [chain(route)],
      },
    ]);
  }
  return [{ id: node.id, name: node.id, kind: node.type, detail: nodeDetail(node), children }];
}

// Every card is 56 px tall (`h-14`), so the lines can meet its middle (`top-7`) and leave it at
// its bottom (`top-14`) whatever hangs off it.
export const CARD =
  "flex h-14 w-52 shrink-0 flex-col justify-center gap-0.5 rounded-lg border bg-card px-3 text-left transition-colors";

/** Cards one under the other, joined by a line down their left side (run order). Keyed by node
 * id, so a card's state (an open menu) stays with its node when the builder moves it. */
function Chain({ cards }: { cards: [string, ReactNode][] }) {
  return (
    <ol className="flex flex-col gap-3">
      {cards.map(([id, card], i) => (
        <li
          key={id}
          className={cn(
            "relative",
            i < cards.length - 1 &&
              "before:absolute before:top-14 before:-bottom-3 before:left-4 before:border-l before:border-border-strong",
          )}
        >
          {card}
        </li>
      ))}
    </ol>
  );
}

/** A card and, to its right, its children (each a chain), joined by elbow lines: a stub from the
 * card to a trunk, and a branch from the trunk to each child. */
function Branch({ card, children }: { card: ReactNode; children: ReactNode[] }) {
  return (
    // Children to the right of the card, or under it (indented) when the map is narrower than
    // 560 px, so a phone scrolls down, not sideways.
    <div className="flex flex-col items-start @min-[560px]:flex-row">
      {card}
      {children.length > 0 ? (
        <ul className="relative mt-3 ml-7 flex flex-col gap-3 before:absolute before:top-7 before:-left-6 before:hidden before:w-3 before:border-t before:border-border-strong @min-[560px]:mt-0 @min-[560px]:ml-6 @min-[560px]:before:block">
          {children.map((child, i) => (
            <li
              key={i}
              className="relative before:absolute before:top-7 before:-left-3 before:w-3 before:border-t before:border-border-strong after:absolute after:top-0 after:-bottom-3 after:-left-3 after:border-l after:border-border-strong first:after:-top-3 last:after:bottom-auto last:after:h-10 @min-[560px]:first:after:top-7 @min-[560px]:last:after:h-7 @min-[560px]:only:after:hidden"
            >
              {child}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function SpecTree({
  spec,
  renderCard,
}: {
  spec: WorkflowSpec;
  renderCard: (node: MapNode) => ReactNode;
}) {
  const render = (node: MapNode): ReactNode => (
    <Branch card={renderCard(node)}>
      {node.children.map((nodes, i) => (
        <Chain key={i} cards={nodes.map((n) => [n.id, render(n)])} />
      ))}
    </Branch>
  );
  return <Chain cards={chain(spec.root).map((n) => [n.id, render(n)])} />;
}
