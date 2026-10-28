"use client";

import type { ReactNode } from "react";

import { Duration, Money, WaitingTime } from "@/components/display";
import { cn } from "@/lib/utils";

import { KindIcon } from "../graph/graph-nodes";
import type { NodeKind } from "../graph/spec-graph";
import { stepUsage, type Step } from "../timeline";
import { StatusIcon, StatusMarker } from "./rail";
import { stepOutline, type StepEntry, type StepRow } from "./step-entries";

/** Indents nested rows: an item's or iteration's steps sit under their node. */
const DEPTH = ["pl-2", "pl-7", "pl-12", "pl-17", "pl-22"];

function indent(depth: number): string {
  return DEPTH[Math.min(depth, DEPTH.length - 1)]!;
}

export function elapsedMs(startedAt: string | null, endedAt: string | null, now: number): number {
  if (!startedAt) return 0;
  const end = endedAt ? Date.parse(endedAt) : now;
  return Math.max(0, end - Date.parse(startedAt));
}

/** The node's kind when the spec is not loaded yet, from what the step did. */
export function guessKind(step: Step): NodeKind {
  if (step.items) return "map";
  if (step.branches) return "parallel";
  if (step.iterations) return "loop";
  if (step.router) return "router";
  if (step.gate) return "gate";
  return step.turns.some((t) => t.kind === "message") ? "agent" : "tool";
}

function StepButton({
  row,
  kind,
  selected,
  now,
  onSelect,
}: {
  row: StepRow;
  kind: NodeKind;
  selected: boolean;
  now: number;
  onSelect: (key: string) => void;
}) {
  const { step } = row;
  const outline = stepOutline(step);
  const usage = stepUsage(step);
  const ms = elapsedMs(step.startedAt, step.endedAt, now);
  return (
    <button
      type="button"
      data-testid="step-row"
      data-key={row.key}
      data-node-id={step.id}
      data-status={step.status}
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect(row.key)}
      className={cn(
        "flex w-full min-w-0 items-start gap-2 rounded-md py-2 pr-2 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50",
        indent(row.depth),
        selected && "bg-muted",
      )}
    >
      <span className="flex h-5 shrink-0 items-center">
        <StatusMarker status={step.status} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-1.5">
          <KindIcon kind={kind} className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 truncate font-mono text-meta font-medium">{row.name}</span>
          {row.itemKind ? (
            <span className="shrink-0 text-caption text-muted-foreground">{row.itemKind}</span>
          ) : null}
        </span>
        {outline ? (
          <span
            data-testid="step-outline"
            className={cn(
              "truncate text-caption",
              step.status === "failed" ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {outline}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 flex-col items-end text-caption text-muted-foreground">
        {step.gate ? (
          <WaitingTime ms={ms} live={step.status === "waiting"} />
        ) : (
          <Duration ms={ms} />
        )}
        {usage ? <Money usage={usage} focusable={false} /> : null}
      </span>
    </button>
  );
}

/** A map item, branch or iteration that holds several steps: a heading over them. */
function ScopeHeading({ entry }: { entry: Extract<StepEntry, { kind: "scope" }> }) {
  return (
    <div
      data-testid="step-scope"
      className={cn(
        "flex min-w-0 items-center gap-2 py-1.5 pr-2 text-caption text-muted-foreground",
        indent(entry.depth),
      )}
    >
      <StatusIcon status={entry.status} small />
      <span className="min-w-0 truncate font-mono font-medium text-foreground">{entry.name}</span>
      {entry.itemKind ? <span className="shrink-0">{entry.itemKind}</span> : null}
    </div>
  );
}

/**
 * The run's steps as a list: status, type, name, one line on what each did, its duration and
 * cost. Map items, branches and iterations nest under their node. Selecting a row shows the step
 * beside the list.
 */
export function StepList({
  entries,
  selected,
  now,
  kindOf,
  onSelect,
  footer,
}: {
  entries: StepEntry[];
  selected: string | null;
  now: number;
  kindOf: (nodeId: string) => NodeKind | null;
  onSelect: (key: string) => void;
  /** After the last step: the live line of a running run. */
  footer?: ReactNode;
}) {
  return (
    <nav aria-label="Steps" className="flex min-w-0 flex-col">
      <ol className="flex min-w-0 flex-col gap-0.5">
        {entries.map((entry) => (
          <li key={`${entry.kind}:${entry.key}`} className="min-w-0">
            {entry.kind === "scope" ? (
              <ScopeHeading entry={entry} />
            ) : (
              <StepButton
                row={entry}
                kind={kindOf(entry.step.id) ?? guessKind(entry.step)}
                selected={entry.key === selected}
                now={now}
                onSelect={onSelect}
              />
            )}
          </li>
        ))}
      </ol>
      {footer ? <div className="mt-3">{footer}</div> : null}
    </nav>
  );
}
