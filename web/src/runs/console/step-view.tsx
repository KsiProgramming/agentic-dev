"use client";

import { CircleAlertIcon, ExternalLinkIcon, RepeatIcon } from "lucide-react";
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/status-badge";
import { cn } from "@/lib/utils";

import { costCaveat, formatCost, formatTokens, usageDetails } from "../cost";
import { formatDuration } from "../summaries";
import {
  stepUsage,
  type Iteration,
  type MapItem,
  type MessageTurn,
  type Step,
  type StepStatus,
  type TokenUsage,
  type ToolTurn,
  type Turn,
} from "../timeline";
import { AgentMessage } from "./agent-message";
import { GateDecision } from "./gate-decision";
import { itemName } from "./item-name";
import { DotMarker, IconMarker, Rail, RailItem, StatusMarker } from "./rail";
import { stepBadge } from "./step-status";
import { ToolCallGroup } from "./tool-calls";
import { toolPreview } from "./tool-describe";

export interface StepViewOptions {
  /** The time, for the duration of what is still running. */
  now: number;
  /** Extra content for a step, e.g. the approval panel of the gate the run waits at. */
  extra?: (step: Step) => ReactNode;
}

function elapsed(startedAt: string, endedAt: string | null, now: number): string {
  const end = endedAt ? Date.parse(endedAt) : now;
  return formatDuration(Math.max(0, end - Date.parse(startedAt)));
}

/** Status words next to a title: only what needs attention. A step that is done says so with its
 * marker alone; one waiting at a gate gets the full badge. */
const STATUS_TEXT: Record<StepStatus, string> = {
  running: "text-status-running",
  waiting: "",
  completed: "",
  failed: "text-status-failed",
  cancelled: "text-status-cancelled",
};

/** A step's or map item's title line: its name, what needs attention, and how long it took. */
function TitleLine({
  title,
  status,
  startedAt,
  endedAt,
  now,
  level,
}: {
  title: ReactNode;
  status: StepStatus;
  startedAt: string;
  endedAt: string | null;
  now: number;
  level: "step" | "item";
}) {
  const Heading = level === "step" ? "h3" : "h4";
  return (
    <div className="flex min-h-5 min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <Heading
        className={cn(
          "min-w-0 font-mono text-[13px] break-all",
          level === "step" ? "font-medium" : "text-foreground",
        )}
      >
        {title}
      </Heading>
      {status === "waiting" ? (
        <StatusBadge status="waiting" label="Needs approval" />
      ) : STATUS_TEXT[status] ? (
        <span aria-hidden="true" className={cn("text-xs", STATUS_TEXT[status])}>
          {stepBadge(status).label}
        </span>
      ) : null}
      <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular-nums">
        {elapsed(startedAt, endedAt, now)}
      </span>
    </div>
  );
}

function UsageFooter({ usage }: { usage: TokenUsage }) {
  const caveat = costCaveat(usage);
  return (
    <p
      data-testid="usage"
      title={usageDetails(usage)}
      className="text-xs text-muted-foreground tabular-nums"
    >
      {formatTokens(usage.inputTokens)} in · {formatTokens(usage.outputTokens)} out ·{" "}
      <span data-testid="usage-cost" title={caveat ?? undefined}>
        {formatCost(usage)}
      </span>
      {caveat ? <span className="sr-only"> ({caveat})</span> : null}
    </p>
  );
}

type Segment = { kind: "message"; turn: MessageTurn } | { kind: "tools"; turns: ToolTurn[] };

/**
 * The turns, with consecutive quiet tool calls (reads, listings, searches) gathered so they show
 * as one group. A call with a preview (a write, a commit, a failure) stands on its own line.
 */
function segments(turns: Turn[]): Segment[] {
  const out: Segment[] = [];
  for (const turn of turns) {
    const last = out.at(-1);
    if (turn.kind === "message") {
      out.push({ kind: "message", turn });
    } else if (toolPreview(turn) !== null) {
      out.push({ kind: "tools", turns: [turn] });
    } else if (last?.kind === "tools" && toolPreview(last.turns[0]!) === null) {
      last.turns.push(turn);
    } else {
      out.push({ kind: "tools", turns: [turn] });
    }
  }
  return out;
}

/** The marker of a group of tool calls: a spinner while one runs, a cross if one failed, a dot. */
function ToolsMarker({ turns }: { turns: ToolTurn[] }) {
  if (turns.some((t) => t.status === "running")) return <StatusMarker status="running" small />;
  if (turns.some((t) => t.status === "failed")) return <StatusMarker status="failed" small />;
  return <DotMarker className="bg-status-succeeded" />;
}

function IterationView({ iteration, options }: { iteration: Iteration; options: StepViewOptions }) {
  return (
    <RailItem data-testid="iteration" marker={<IconMarker icon={RepeatIcon} />}>
      <p className="flex min-h-5 items-center gap-1.5 text-xs font-medium text-muted-foreground">
        Iteration {iteration.index}
        {iteration.conditionMet !== null ? (
          <span className="font-normal">
            · condition {iteration.conditionMet ? "met" : "not met"}
          </span>
        ) : null}
      </p>
      <StepList steps={iteration.steps} options={options} className="mt-3" />
    </RailItem>
  );
}

function MapItemView({ item, options }: { item: MapItem; options: StepViewOptions }) {
  const { name, kind } = itemName(item.item, item.index);
  return (
    <RailItem
      data-testid="map-item"
      data-status={item.status}
      marker={<StatusMarker status={item.status} small />}
    >
      <TitleLine
        title={
          <>
            {name}
            {kind ? (
              <span className="ml-2 font-sans font-normal text-muted-foreground">{kind}</span>
            ) : null}
          </>
        }
        status={item.status}
        startedAt={item.startedAt}
        endedAt={item.endedAt}
        now={options.now}
        level="item"
      />
      <div className="mt-3 flex min-w-0 flex-col gap-3">
        {item.error ? <ErrorLine error={item.error} /> : null}
        {item.steps.length === 1 ? (
          // One step per item (the usual map body): the item's title is enough.
          <div
            data-testid="step"
            data-node-id={item.steps[0]!.id}
            className="flex min-w-0 flex-col gap-3"
          >
            <StepBody step={item.steps[0]!} options={options} />
          </div>
        ) : (
          <StepList steps={item.steps} options={options} />
        )}
      </div>
    </RailItem>
  );
}

function ErrorLine({ error }: { error: string }) {
  return (
    <p className="flex items-start gap-1.5 text-[13px] break-words text-destructive">
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </p>
  );
}

/** What a node did, in order, on its own rail: messages, tool calls, map items, iterations;
 * then its gate, pull request, error and token usage. */
export function StepBody({ step, options }: { step: Step; options: StepViewOptions }) {
  const live = step.status === "running";
  const entries = segments(step.turns);
  const usage = stepUsage(step);
  const hasRail =
    entries.length > 0 || (step.items?.length ?? 0) > 0 || (step.iterations?.length ?? 0) > 0;
  return (
    <>
      {hasRail ? (
        <Rail>
          {entries.map((segment) =>
            segment.kind === "message" ? (
              <RailItem key={segment.turn.key} marker={<DotMarker />}>
                <AgentMessage text={segment.turn.text} streaming={live && !segment.turn.final} />
              </RailItem>
            ) : (
              <RailItem
                key={segment.turns[0]!.key}
                marker={<ToolsMarker turns={segment.turns} />}
                // Tool lines have their own padding: line the marker up with their text.
                markerClassName="top-1"
                className="pl-5.5"
              >
                <ToolCallGroup turns={segment.turns} />
              </RailItem>
            ),
          )}
          {step.items?.map((item) => (
            <MapItemView key={item.index} item={item} options={options} />
          ))}
          {step.iterations?.map((iteration) => (
            <IterationView key={iteration.index} iteration={iteration} options={options} />
          ))}
        </Rail>
      ) : null}
      {step.gate ? <GateDecision gate={step.gate} /> : null}
      {options.extra?.(step)}
      {step.prUrl ? (
        <a
          href={step.prUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex w-fit items-center gap-1 font-mono text-[13px] break-all text-primary underline-offset-4 hover:underline"
        >
          {step.prUrl}
          <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
        </a>
      ) : null}
      {step.error ? <ErrorLine error={step.error} /> : null}
      {usage ? <UsageFooter usage={usage} /> : null}
    </>
  );
}

/** One node of the run on the run's rail: its status marker and title, then what it did. */
export function StepView({ step, options }: { step: Step; options: StepViewOptions }) {
  return (
    <RailItem
      data-testid="step"
      data-node-id={step.id}
      data-status={step.status}
      marker={<StatusMarker status={step.status} />}
    >
      <TitleLine
        title={step.id}
        status={step.status}
        startedAt={step.startedAt}
        endedAt={step.endedAt}
        now={options.now}
        level="step"
      />
      <div className="mt-3 flex min-w-0 flex-col gap-3">
        <StepBody step={step} options={options} />
      </div>
    </RailItem>
  );
}

export function StepList({
  steps,
  options,
  className,
}: {
  steps: Step[];
  options: StepViewOptions;
  className?: string;
}) {
  if (steps.length === 0) return null;
  return (
    <Rail className={cn("[--rail-gap:--spacing(6)]", className)}>
      {steps.map((step) => (
        <StepView key={step.id} step={step} options={options} />
      ))}
    </Rail>
  );
}
