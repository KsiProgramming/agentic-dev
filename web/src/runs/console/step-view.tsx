"use client";

import { CircleAlertIcon, ExternalLinkIcon, RepeatIcon } from "lucide-react";
import type { ReactNode } from "react";

import { StatusBadge } from "@/components/status-badge";

import { formatDuration } from "../summaries";
import type {
  Iteration,
  MapItem,
  MessageTurn,
  Step,
  StepStatus,
  TokenUsage,
  ToolTurn,
  Turn,
} from "../timeline";
import { AgentMessage } from "./agent-message";
import { stepBadge } from "./step-status";
import { ToolCallGroup } from "./tool-calls";

export interface StepViewOptions {
  /** The time, for the duration of what is still running. */
  now: number;
  /** Extra content for a step, e.g. the approval panel of the gate the run waits at. */
  extra?: (step: Step) => ReactNode;
}

const numbers = new Intl.NumberFormat("en-US");

function elapsed(startedAt: string, endedAt: string | null, now: number): string {
  const end = endedAt ? Date.parse(endedAt) : now;
  return formatDuration(Math.max(0, end - Date.parse(startedAt)));
}

/** What a map item is called: a string item as is, an object by its `path`, `name` or `id`
 * (with its `kind`, if any), anything else as JSON. */
function itemLabel(item: unknown, index: number): ReactNode {
  if (typeof item === "string") return item;
  if (item && typeof item === "object" && !Array.isArray(item)) {
    const fields = item as Record<string, unknown>;
    const name = [fields.path, fields.name, fields.id].find((v) => typeof v === "string");
    if (typeof name === "string") {
      return (
        <>
          {name}
          {typeof fields.kind === "string" ? (
            <span className="ml-2 font-sans font-normal text-muted-foreground">{fields.kind}</span>
          ) : null}
        </>
      );
    }
  }
  if (item === undefined) return `Item ${index + 1}`;
  return JSON.stringify(item);
}

function StatusLine({
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
  const badge = stepBadge(status);
  const Heading = level === "step" ? "h3" : "h4";
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <Heading className="min-w-0 font-mono text-[13px] font-medium break-all">{title}</Heading>
      <span className="ml-auto flex shrink-0 items-center gap-2 text-[13px]">
        <span className="text-muted-foreground tabular-nums">
          {elapsed(startedAt, endedAt, now)}
        </span>
        <StatusBadge status={badge.status} label={badge.label} />
      </span>
    </div>
  );
}

function UsageFooter({ usage }: { usage: TokenUsage }) {
  return (
    <p data-testid="usage" className="text-xs text-muted-foreground tabular-nums">
      {numbers.format(usage.inputTokens)} in · {numbers.format(usage.outputTokens)} out tokens
    </p>
  );
}

type Segment = { kind: "message"; turn: MessageTurn } | { kind: "tools"; turns: ToolTurn[] };

/** The turns with consecutive tool calls gathered, so they show as one group. */
function segments(turns: Turn[]): Segment[] {
  const out: Segment[] = [];
  for (const turn of turns) {
    const last = out.at(-1);
    if (turn.kind === "message") out.push({ kind: "message", turn });
    else if (last?.kind === "tools") last.turns.push(turn);
    else out.push({ kind: "tools", turns: [turn] });
  }
  return out;
}

function IterationView({ iteration, options }: { iteration: Iteration; options: StepViewOptions }) {
  return (
    <li data-testid="iteration" className="flex flex-col gap-2">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <RepeatIcon aria-hidden="true" className="size-3.5" />
        Iteration {iteration.index}
        {iteration.conditionMet !== null ? (
          <span className="font-normal">
            · condition {iteration.conditionMet ? "met" : "not met"}
          </span>
        ) : null}
      </p>
      <StepList steps={iteration.steps} options={options} />
    </li>
  );
}

function MapItemView({ item, options }: { item: MapItem; options: StepViewOptions }) {
  return (
    <li data-testid="map-item" className="flex flex-col gap-2 rounded-lg border p-3">
      <StatusLine
        title={itemLabel(item.item, item.index)}
        status={item.status}
        startedAt={item.startedAt}
        endedAt={item.endedAt}
        now={options.now}
        level="item"
      />
      {item.error ? <ErrorLine error={item.error} /> : null}
      {item.steps.length === 1 ? (
        // One step per item (the usual map body): the item's header is enough.
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
    </li>
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

/** What a node did, in order: messages, tool calls, nested items and iterations. */
function StepBody({ step, options }: { step: Step; options: StepViewOptions }) {
  const live = step.status === "running";
  return (
    <>
      {segments(step.turns).map((segment) =>
        segment.kind === "message" ? (
          <AgentMessage
            key={segment.turn.key}
            text={segment.turn.text}
            streaming={live && !segment.turn.final}
          />
        ) : (
          <ToolCallGroup key={segment.turns[0]!.key} turns={segment.turns} />
        ),
      )}
      {step.items && step.items.length > 0 ? (
        <ol aria-label={`Items of ${step.id}`} className="flex flex-col gap-3">
          {step.items.map((item) => (
            <MapItemView key={item.index} item={item} options={options} />
          ))}
        </ol>
      ) : null}
      {step.iterations && step.iterations.length > 0 ? (
        <ol aria-label={`Iterations of ${step.id}`} className="flex flex-col gap-4">
          {step.iterations.map((iteration) => (
            <IterationView key={iteration.index} iteration={iteration} options={options} />
          ))}
        </ol>
      ) : null}
      {step.gate ? (
        <p className="text-[13px]">
          <span className="font-medium">{step.gate.title}</span>
          {step.gate.decision ? (
            <span className="text-muted-foreground">
              {" "}
              · {step.gate.decision === "approve" ? "Approved" : "Rejected"}
              {step.gate.comment ? `: ${step.gate.comment}` : ""}
            </span>
          ) : null}
        </p>
      ) : null}
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
      {step.usage ? <UsageFooter usage={step.usage} /> : null}
    </>
  );
}

/** One node of the run: its status line, then what it did. */
export function StepView({ step, options }: { step: Step; options: StepViewOptions }) {
  return (
    <li
      data-testid="step"
      data-node-id={step.id}
      data-status={step.status}
      className="flex min-w-0 flex-col gap-3"
    >
      <StatusLine
        title={step.id}
        status={step.status}
        startedAt={step.startedAt}
        endedAt={step.endedAt}
        now={options.now}
        level="step"
      />
      <div className="flex min-w-0 flex-col gap-3 border-l pl-4">
        <StepBody step={step} options={options} />
      </div>
    </li>
  );
}

export function StepList({ steps, options }: { steps: Step[]; options: StepViewOptions }) {
  if (steps.length === 0) return null;
  return (
    <ol className="flex min-w-0 flex-col gap-5">
      {steps.map((step) => (
        <StepView key={step.id} step={step} options={options} />
      ))}
    </ol>
  );
}
