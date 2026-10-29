"use client";

import type { ReactNode } from "react";

import { Duration, Money } from "@/components/display";
import { cn } from "@/lib/utils";

import { stepUsage, type Step } from "../timeline";
import { elapsedMs } from "../console/step-list";
import { KindIcon, kindLabel, statusLabel } from "./node-kinds";
import { nodeStatuses, routeStates, type NodeState, type NodeStatus } from "./node-status";
import {
  nodeDetail,
  routeNodeId,
  routesOf,
  type NodeKind,
  type SpecNode,
  type WorkflowSpec,
} from "./spec-graph";

/** One card of the map: a spec node, or a router's route; its children hang off it. */
interface MapNode {
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
  if (node.type === "loop" || node.type === "map") children = [chain(node.body)];
  if (node.type === "parallel") children = node.branches.map(chain);
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

/** Every run of each node, nested ones included. */
function runsById(steps: Step[]): Map<string, Step[]> {
  const byId = new Map<string, Step[]>();
  const visit = (list: Step[]) => {
    for (const step of list) {
      byId.set(step.id, [...(byId.get(step.id) ?? []), step]);
      for (const item of step.items ?? []) visit(item.steps);
      for (const branch of step.branches ?? []) visit(branch.steps);
      for (const iteration of step.iterations ?? []) visit(iteration.steps);
      if (step.router) visit(step.router.steps);
    }
  };
  visit(steps);
  return byId;
}

/** The status dot: filled in the status's colour once the node ran; hollow before; dashed on a
 * route its router did not take. Colour is never alone: the card's name says the status to
 * screen readers. */
const DOT: Record<NodeStatus, string> = {
  running: "bg-status-running motion-safe:animate-pulse",
  waiting: "bg-status-waiting",
  completed: "bg-status-succeeded",
  failed: "bg-status-failed",
  cancelled: "bg-status-cancelled",
  not_started: "border border-border-strong bg-transparent",
  skipped: "border border-dashed border-border-strong bg-transparent",
};

function Dot({ status }: { status: NodeStatus }) {
  return <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", DOT[status])} />;
}

/** What a node did once it ran ("8s · $0.031"), how far a container got, else what it does. */
function nodeLine(node: MapNode, state: NodeState | undefined, runs: Step[], now: number) {
  if (state?.summary) return state.summary;
  if (runs.length === 0)
    return node.detail || kindLabel(node.kind === "route" ? "router" : node.kind);
  const usage = runs.map(stepUsage).find(Boolean) ?? null;
  const ms = runs.reduce((sum, run) => sum + elapsedMs(run.startedAt, run.endedAt, now), 0);
  return (
    <>
      {runs.length > 1 ? `${runs.length} runs · ` : null}
      <Duration ms={ms} />
      {usage ? (
        <>
          {" · "}
          <Money usage={usage} focusable={false} />
        </>
      ) : null}
    </>
  );
}

// Every card is 56 px tall (`h-14`), so the lines can meet its middle (`top-7`) and leave it at
// its bottom (`top-14`) whatever hangs off it.
const CARD =
  "flex h-14 w-52 shrink-0 flex-col justify-center gap-0.5 rounded-lg border bg-card px-3 text-left transition-colors";

/** Cards one under the other, joined by a line down their left side (run order). */
function Chain({ cards }: { cards: ReactNode[] }) {
  return (
    <ol className="flex flex-col gap-3">
      {cards.map((card, i) => (
        <li
          key={i}
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

/**
 * The run's workflow as a map like Claude Code's agent map (design-language.md → Components →
 * Run map): the steps top to bottom in run order, a container's body, branches or routes
 * hanging off it to the right. Each card shows its status, name and what it did, and is a
 * button that selects its step (`onOpen` with the node id). No pan or zoom: it scrolls in its
 * box.
 */
export function RunMap({
  spec,
  steps,
  selected = null,
  onOpen,
  now,
}: {
  spec: WorkflowSpec;
  steps: Step[];
  selected?: string | null;
  onOpen: (nodeId: string) => void;
  now: number;
}) {
  const states = new Map([...nodeStatuses(spec, steps), ...routeStates(spec, steps)]);
  const runs = runsById(steps);

  const renderChain = (nodes: MapNode[]): ReactNode => <Chain cards={nodes.map(render)} />;

  function render(node: MapNode): ReactNode {
    const state = states.get(node.id);
    const status = state?.status ?? "not_started";
    const children = node.children.map(renderChain);
    if (node.kind === "route") {
      return (
        <Branch
          card={
            <div
              data-testid="map-route"
              data-status={status}
              className={cn(
                CARD,
                "border-dashed bg-surface-subtle",
                status === "skipped" && "opacity-70",
              )}
            >
              <span className="flex items-center gap-2">
                <Dot status={status} />
                <span className="truncate font-mono text-meta font-medium">{node.name}</span>
              </span>
              <span className="pl-4 text-caption text-foreground-secondary">
                {status === "skipped" ? "Skipped" : "Route"}
              </span>
            </div>
          }
        >
          {children}
        </Branch>
      );
    }
    const isSelected = selected === node.id;
    return (
      <Branch
        card={
          <button
            type="button"
            data-testid="map-node"
            data-node={node.id}
            data-status={status}
            aria-pressed={isSelected}
            aria-label={`${node.name}, ${statusLabel(status)}, ${kindLabel(node.kind as NodeKind)}`}
            onClick={() => onOpen(node.id)}
            className={cn(
              CARD,
              "hover:bg-muted",
              isSelected && "ring-2 ring-primary",
              status === "skipped" && "text-muted-foreground",
            )}
          >
            <span className="flex min-w-0 items-center gap-2">
              <Dot status={status} />
              <span className="truncate font-mono text-meta font-medium">{node.name}</span>
              <KindIcon
                kind={node.kind as NodeKind}
                className="ml-auto size-3.5 shrink-0 text-muted-foreground"
              />
            </span>
            <span className="truncate pl-4 text-caption text-foreground-secondary">
              {status === "skipped"
                ? "Skipped"
                : nodeLine(node, state, runs.get(node.id) ?? [], now)}
            </span>
          </button>
        }
      >
        {children}
      </Branch>
    );
  }

  // A route its router did not take is not work left to do: it is counted apart.
  const all = [...nodeStatuses(spec, steps).values()];
  const nodes = all.filter((s) => s.status !== "skipped");
  const skipped = all.length - nodes.length;
  const done = nodes.filter((s) => s.status === "completed").length;
  const failed = nodes.filter((s) => s.status === "failed").length;
  const footer = [
    done === nodes.length
      ? `${nodes.length} steps · All completed`
      : `${done} of ${nodes.length} steps done`,
    failed > 0 ? `${failed} failed` : null,
    skipped > 0 ? `${skipped} skipped` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      data-testid="run-map"
      role="region"
      aria-label="Workflow map"
      className="flex max-h-[min(75svh,800px)] min-h-60 flex-col overflow-hidden bg-background"
    >
      <div className="@container min-h-0 flex-1 overflow-auto p-4">
        {renderChain(chain(spec.root))}
      </div>
      <p className="border-t bg-surface-subtle px-4 py-2 text-caption text-muted-foreground">
        {footer}
      </p>
    </div>
  );
}
