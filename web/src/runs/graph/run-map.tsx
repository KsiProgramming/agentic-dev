"use client";

import type { ReactNode } from "react";

import { Duration, Money } from "@/components/display";
import { cn } from "@/lib/utils";

import {
  stepsUsage,
  stepUsage,
  type OrchestratorTask,
  type Step,
  type TaskStatus,
} from "../timeline";
import { elapsedMs } from "../console/step-list";
import { KindIcon, kindLabel, statusLabel } from "./node-kinds";
import { nodeStatuses, routeStates, type NodeState, type NodeStatus } from "./node-status";
import { type NodeKind, type WorkflowSpec } from "./spec-graph";
import { SpecView } from "./spec-flow";
import { CARD, type MapNode } from "./spec-tree";

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
      if (step.subflow) visit(step.subflow.steps);
      for (const task of step.orchestrator?.tasks ?? []) visit(task.steps);
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

/** A task's status as a map dot: not started yet is hollow, dropped by a replan dashed (it
 * neither ran nor failed). */
function taskDot(status: TaskStatus): NodeStatus {
  if (status === "pending") return "not_started";
  if (status === "dropped") return "skipped";
  return status;
}

/** An orchestrator's tasks under its card, as they are planned (6.4): each a small card with
 * its status, id, title and what it cost, that selects its worker's step. Titles are the hub's
 * words: text only. */
function TaskCards({
  orchestratorId,
  tasks,
  selected,
  now,
  onOpen,
}: {
  orchestratorId: string;
  tasks: OrchestratorTask[];
  selected: OrchestratorTask | null;
  now: number;
  onOpen?: (task: OrchestratorTask) => void;
}) {
  return (
    <ul
      aria-label={`Tasks of ${orchestratorId}`}
      data-testid="map-tasks"
      className="mt-2 ml-7 flex w-52 flex-col gap-1"
    >
      {tasks.map((task) => {
        const status = taskDot(task.status);
        const usage = stepsUsage(task.steps);
        const ran = task.steps.length > 0 && onOpen;
        const line =
          task.status === "dropped" ? (
            "Dropped"
          ) : task.startedAt ? (
            <>
              <Duration ms={elapsedMs(task.startedAt, task.endedAt, now)} />
              {usage ? (
                <>
                  {" · "}
                  <Money usage={usage} focusable={false} />
                </>
              ) : null}
            </>
          ) : (
            "Not started"
          );
        const body = (
          <>
            <span className="flex min-w-0 items-center gap-2">
              <Dot status={status} />
              <span className="shrink-0 font-mono text-caption font-medium">
                {task.id}
                <span className="sr-only">, {statusLabel(status)},</span>
              </span>
              <span className="min-w-0 truncate text-caption text-foreground-secondary">
                {task.title}
              </span>
            </span>
            <span className="truncate pl-4 text-caption text-foreground-secondary">
              {line}
              <span className="sr-only">, task</span>
            </span>
          </>
        );
        const card = cn(
          "flex w-full min-w-0 flex-col gap-0.5 rounded-md border bg-card px-2.5 py-1.5 text-left",
          status === "skipped" && "border-dashed text-muted-foreground",
        );
        return (
          <li key={task.id} data-testid="map-task" data-task={task.id} data-status={task.status}>
            {ran ? (
              <button
                type="button"
                aria-pressed={selected === task}
                onClick={() => onOpen(task)}
                className={cn(card, "hover:bg-muted", selected === task && "ring-2 ring-primary")}
              >
                {body}
              </button>
            ) : (
              <div className={card}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
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
  selectedTask = null,
  onOpen,
  onOpenTask,
  now,
  layout,
}: {
  spec: WorkflowSpec;
  steps: Step[];
  selected?: string | null;
  /** The orchestrator task the shown step runs for. */
  selectedTask?: OrchestratorTask | null;
  onOpen: (nodeId: string) => void;
  /** Selects a task's worker step. */
  onOpenTask?: (task: OrchestratorTask) => void;
  now: number;
  /** Forces the flow or the tree (tests, previews); by default the pane's width picks. */
  layout?: "flow" | "tree";
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
    const isSelected = selected === node.id && selectedTask === null;
    const tasks =
      node.kind === "orchestrator" ? runs.get(node.id)?.at(-1)?.orchestrator?.tasks : null;
    const card = (
      <button
        type="button"
        data-testid="map-node"
        data-node={node.id}
        data-status={status}
        aria-pressed={isSelected}
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
          {/* The name comes from the card's own text, so it holds what is visible (WCAG 2.5.3):
              "each, Done, 2 of 2 items, map". Status and kind are words for screen readers. */}
          <span className="truncate font-mono text-meta font-medium">
            {node.name}
            <span className="sr-only">, {statusLabel(status)},</span>
          </span>
          <KindIcon
            kind={node.kind as NodeKind}
            className="ml-auto size-3.5 shrink-0 text-muted-foreground"
          />
        </span>
        <span className="truncate pl-4 text-caption text-foreground-secondary">
          {status === "skipped" ? "Skipped" : nodeLine(node, state, runs.get(node.id) ?? [], now)}
          <span className="sr-only">, {kindLabel(node.kind as NodeKind)}</span>
        </span>
      </button>
    );
    if (!tasks || tasks.length === 0) return card;
    return (
      <div className="flex flex-col">
        {card}
        <TaskCards
          orchestratorId={node.id}
          tasks={tasks}
          selected={selectedTask}
          now={now}
          onOpen={onOpenTask}
        />
      </div>
    );
  }

  // A route its router did not take is not work left to do: it is counted apart.
  const all = [...nodeStatuses(spec, steps).values()];
  const nodes = all.filter((s) => s.status !== "skipped");
  const skipped = all.length - nodes.length;
  const done = nodes.filter((s) => s.status === "completed").length;
  const failed = nodes.filter((s) => s.status === "failed").length;
  const tasks = [...runs.values()].flat().flatMap((step) => step.orchestrator?.tasks ?? []);
  const tasksDone = tasks.filter((t) => t.status === "completed").length;
  const tasksDropped = tasks.filter((t) => t.status === "dropped").length;
  const footer = [
    done === nodes.length
      ? `${nodes.length} steps · All completed`
      : `${done} of ${nodes.length} steps done`,
    failed > 0 ? `${failed} failed` : null,
    skipped > 0 ? `${skipped} skipped` : null,
    tasks.length > 0
      ? `${tasksDone} of ${tasks.length} ${tasks.length === 1 ? "task" : "tasks"} done${
          tasksDropped > 0 ? ` (${tasksDropped} dropped)` : ""
        }`
      : null,
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
        <SpecView
          spec={spec}
          renderCard={renderCard}
          isSkipped={(route) => states.get(route)?.status === "skipped"}
          layout={layout}
        />
      </div>
      <p className="border-t bg-surface-subtle px-4 py-2 text-caption text-muted-foreground">
        {footer}
      </p>
    </div>
  );
}
