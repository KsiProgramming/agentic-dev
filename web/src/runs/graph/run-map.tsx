"use client";

import type { ReactNode } from "react";

import { Duration, Money } from "@/components/display";
import { cn } from "@/lib/utils";

import { stepUsage, type Step } from "../timeline";
import { elapsedMs } from "../console/step-list";
import { KindIcon, kindLabel, statusLabel } from "./node-kinds";
import { nodeStatuses, routeStates, type NodeState, type NodeStatus } from "./node-status";
import { type NodeKind, type WorkflowSpec } from "./spec-graph";
import { CARD, SpecTree, type MapNode } from "./spec-tree";

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

  function renderCard(node: MapNode): ReactNode {
    const state = states.get(node.id);
    const status = state?.status ?? "not_started";
    if (node.kind === "route") {
      return (
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
      );
    }
    const isSelected = selected === node.id;
    return (
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
          {status === "skipped" ? "Skipped" : nodeLine(node, state, runs.get(node.id) ?? [], now)}
        </span>
      </button>
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
        <SpecTree spec={spec} renderCard={renderCard} />
      </div>
      <p className="border-t bg-surface-subtle px-4 py-2 text-caption text-muted-foreground">
        {footer}
      </p>
    </div>
  );
}
