"use client";

import { GitMergeIcon } from "lucide-react";

import { Duration, Money, TruncatedPath } from "@/components/display";
import { cn } from "@/lib/utils";

import {
  stepsUsage,
  type Integration,
  type OrchestratorInfo,
  type OrchestratorTask,
  type PlanRound,
  type Step,
} from "../timeline";
import { StatusMarker } from "./rail";
import { stepRows, type StepEntry } from "./step-entries";
import { elapsedMs } from "./step-list";

function count(n: number, word: string, plural = `${word}s`): string {
  return `${n} ${n === 1 ? word : plural}`;
}

/** The step a task's row selects: its worker's first step. */
function firstStepKeys(entries: StepEntry[]): Map<OrchestratorTask, string> {
  const keys = new Map<OrchestratorTask, string>();
  for (const row of stepRows(entries)) {
    if (row.task && !keys.has(row.task)) keys.set(row.task, row.key);
  }
  return keys;
}

/** "6 tasks · 2 rounds · 4 tool calls · 1m 02s · $0.42": what the orchestrator did in all. */
function Totals({ step, info, now }: { step: Step; info: OrchestratorInfo; now: number }) {
  const all = info.tasks.flatMap((t) => t.steps);
  const toolCalls = all.reduce((n, s) => n + s.turns.filter((t) => t.kind === "tool").length, 0);
  const usage = stepsUsage(all);
  return (
    <p data-testid="orchestrator-totals" className="text-meta text-foreground-secondary">
      {count(info.tasks.length, "task")}
      {info.rounds.length > 1 ? ` · ${count(info.rounds.length, "round")}` : ""} ·{" "}
      {count(toolCalls, "tool call")} ·{" "}
      <Duration ms={elapsedMs(step.startedAt, step.endedAt, now)} />
      {usage ? (
        <>
          {" "}
          · <Money usage={usage} />
        </>
      ) : null}
    </p>
  );
}

function TaskLine({
  task,
  stepKey,
  now,
  onSelect,
}: {
  task: OrchestratorTask;
  stepKey: string | undefined;
  now: number;
  onSelect: (key: string) => void;
}) {
  const quiet = task.status === "dropped" || task.status === "pending";
  const usage = stepsUsage(task.steps);
  const body = (
    <>
      <span className="flex h-5 shrink-0 items-center">
        <StatusMarker status={task.status} small />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              "shrink-0 font-mono text-meta font-medium",
              quiet && "text-muted-foreground",
            )}
          >
            {task.id}
          </span>
          {/* The hub's words: text only (mission principle 5). */}
          <span
            className={cn(
              "min-w-0 truncate text-meta",
              quiet ? "text-muted-foreground" : "text-foreground-secondary",
            )}
          >
            {task.title}
          </span>
        </span>
        {task.status === "dropped" ? (
          <span className="text-caption text-muted-foreground">
            Dropped: the round stopped before it started
          </span>
        ) : task.status === "failed" && task.error ? (
          <span className="truncate text-caption text-status-failed">{task.error}</span>
        ) : null}
      </span>
      {task.startedAt ? (
        <span className="flex shrink-0 flex-col items-end text-caption text-foreground-secondary">
          <Duration ms={elapsedMs(task.startedAt, task.endedAt, now)} />
          {usage ? <Money usage={usage} focusable={false} /> : null}
        </span>
      ) : null}
    </>
  );
  return (
    <li data-testid="orchestrator-task" data-task={task.id} data-status={task.status}>
      {stepKey ? (
        <button
          type="button"
          onClick={() => onSelect(stepKey)}
          className="flex w-full min-w-0 items-start gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          {body}
        </button>
      ) : (
        <div className="flex w-full min-w-0 items-start gap-2 px-2 py-1.5">{body}</div>
      )}
    </li>
  );
}

function IntegrationLine({
  integration,
  taskIds,
}: {
  integration: Integration;
  /** This orchestrator's tasks: in a loop (6.9), `merged` also lists earlier iterations'. */
  taskIds: Set<string>;
}) {
  const { branch, empty, conflicts } = integration;
  const merged = integration.merged.filter((id) => taskIds.has(id));
  const before = integration.merged.filter((id) => !taskIds.has(id));
  return (
    <div data-testid="orchestrator-integration" className="flex min-w-0 flex-col gap-1 text-meta">
      <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-foreground-secondary">
        <GitMergeIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
        {merged.length > 0 ? (
          <>
            Merged <span className="font-mono text-foreground">{merged.join(", ")}</span> into
          </>
        ) : (
          "Nothing merged into"
        )}{" "}
        <span className="font-mono break-all text-foreground">{branch}</span>
        {before.length > 0 ? (
          <>
            , on top of <span className="font-mono text-foreground">{before.join(", ")}</span>
          </>
        ) : null}
      </p>
      {empty.length > 0 ? (
        <p className="pl-5.5 text-caption text-muted-foreground">
          No changes from <span className="font-mono">{empty.join(", ")}</span>
        </p>
      ) : null}
      {conflicts.map(({ id, paths }) => (
        <div key={id} className="flex min-w-0 flex-col pl-5.5 text-caption">
          <p className="text-status-failed">
            <span className="font-mono">{id}</span> conflicts with earlier tasks on:
          </p>
          <ul className="flex min-w-0 flex-col">
            {paths.slice(0, 10).map((path) => (
              <li key={path} className="min-w-0">
                <TruncatedPath path={path} focusable={false} />
              </li>
            ))}
            {paths.length > 10 ? (
              <li className="text-muted-foreground">and {paths.length - 10} more</li>
            ) : null}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Round({
  round,
  tasks,
  taskIds,
  heading,
  keys,
  now,
  onSelect,
}: {
  round: PlanRound;
  tasks: OrchestratorTask[];
  taskIds: Set<string>;
  heading: boolean;
  keys: Map<OrchestratorTask, string>;
  now: number;
  onSelect: (key: string) => void;
}) {
  const label = `Round ${round.round}`;
  return (
    <section
      aria-label={heading ? label : "Plan"}
      data-testid="orchestrator-round"
      className="flex min-w-0 flex-col gap-2"
    >
      {heading ? <h3 className="text-meta font-medium">{label}</h3> : null}
      {round.replan ? (
        <div className="flex min-w-0 flex-col gap-0.5 text-meta text-foreground-secondary">
          <p>Replanned after:</p>
          <ul className="flex min-w-0 flex-col gap-0.5 pl-4">
            {round.replan.failed.map(({ id, error }) => (
              <li key={id} className="min-w-0 truncate">
                <span className="font-mono">{id}</span> failed: {error}
              </li>
            ))}
            {round.replan.dropped.length > 0 ? (
              <li>
                <span className="font-mono">{round.replan.dropped.join(", ")}</span> dropped
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
      {round.reason ? (
        <p className="text-meta text-foreground-secondary">Why this plan: {round.reason}</p>
      ) : null}
      {tasks.length > 0 ? (
        <ul
          aria-label={`Tasks of ${label.toLowerCase()}`}
          className="flex min-w-0 flex-col gap-0.5"
        >
          {tasks.map((task) => (
            <TaskLine
              key={task.id}
              task={task}
              stepKey={keys.get(task)}
              now={now}
              onSelect={onSelect}
            />
          ))}
        </ul>
      ) : round.taskIds.length === 0 && round.reason !== null ? (
        <p className="text-meta text-muted-foreground">The hub planned no task.</p>
      ) : null}
      {round.integration ? (
        <IntegrationLine integration={round.integration} taskIds={taskIds} />
      ) : null}
    </section>
  );
}

/** In a later iteration of its loop (6.9): which iteration, and what the hub planned again from. */
function IterationLine({ iteration, feedback }: { iteration: number; feedback: string | null }) {
  return (
    <section
      aria-label={`Iteration ${iteration}`}
      data-testid="orchestrator-iteration"
      className="flex min-w-0 flex-col gap-1 text-meta"
    >
      <h3 className="font-medium">Iteration {iteration}</h3>
      {feedback ? (
        <>
          <p className="text-foreground-secondary">
            Planned again after the last iteration ended with:
          </p>
          {/* Model output (a review): text only (mission principle 5). */}
          <p
            data-testid="orchestrator-feedback"
            className="rounded-md border border-border bg-surface-subtle px-3 py-2 break-words whitespace-pre-wrap text-foreground-secondary"
          >
            {feedback}
          </p>
        </>
      ) : (
        <p className="text-foreground-secondary">Planned again on top of the work merged so far.</p>
      )}
    </section>
  );
}

/**
 * An orchestrator's Output (6.4): what it did in all, then (in a later iteration of its loop,
 * 6.9) what the last iteration ended with, then each round: why a replan was made, the hub's
 * reason, its tasks (each selecting its worker's step, with its duration and cost) and the
 * integration branch after it. Titles, reasons, reviews and errors are model or repo output,
 * shown as text, never Markdown or HTML.
 */
export function OrchestratorPlan({
  step,
  info,
  entries,
  now,
  onSelect,
}: {
  step: Step;
  info: OrchestratorInfo;
  entries: StepEntry[];
  now: number;
  onSelect: (key: string) => void;
}) {
  if (info.rounds.length === 0 && info.tasks.length === 0) {
    return (
      <p className="text-body text-muted-foreground">
        {step.status === "running" ? "The hub is planning the tasks…" : "No plan was made."}
      </p>
    );
  }
  const keys = firstStepKeys(entries);
  const byRound = info.rounds.length > 1;
  const taskIds = new Set(info.tasks.map((t) => t.id));
  return (
    <div data-testid="orchestrator-plan" className="flex min-w-0 flex-col gap-4">
      <Totals step={step} info={info} now={now} />
      {info.iteration !== null && info.iteration > 1 ? (
        <IterationLine iteration={info.iteration} feedback={info.feedback} />
      ) : null}
      {info.rounds.map((round) => (
        <Round
          key={round.round}
          round={round}
          tasks={info.tasks.filter((t) => t.round === round.round)}
          taskIds={taskIds}
          heading={byRound}
          keys={keys}
          now={now}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
