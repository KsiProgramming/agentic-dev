"use client";

import type { ReactNode } from "react";

import { Duration, Money, WaitingTime } from "@/components/display";
import { cn } from "@/lib/utils";

import { KindIcon } from "../graph/node-kinds";
import type { NodeKind } from "../graph/spec-graph";
import { stepUsage, type Step } from "../timeline";
import { StatusMarker } from "./rail";
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
  if (step.orchestrator) return "orchestrator";
  if (step.subflow) return "subflow";
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
        "flex w-full min-w-0 items-start gap-2 rounded-md py-2 pr-2 text-left hover:bg-muted",
        indent(row.depth),
        // Selected: a tint and a 2 px ink bar on the left edge (design-language.md → Rows).
        selected && "bg-surface-subtle shadow-[inset_2px_0_0_var(--primary)] hover:bg-muted",
      )}
    >
      <span className="flex h-5 shrink-0 items-center">
        <StatusMarker status={step.status} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex min-w-0 items-center gap-1.5">
          <KindIcon kind={kind} className="size-3.5 shrink-0 text-foreground-secondary" />
          <span className="min-w-0 truncate font-mono text-meta font-medium">{row.name}</span>
          {row.itemKind ? (
            <span className="shrink-0 text-caption text-muted-foreground">{row.itemKind}</span>
          ) : null}
        </span>
        {outline ? (
          <span
            data-testid="step-outline"
            className={cn(
              "truncate text-meta",
              step.status === "failed" ? "text-status-failed" : "text-foreground-secondary",
            )}
          >
            {outline}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 flex-col items-end text-caption text-foreground-secondary">
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

/** A map item, branch or iteration that holds several steps, an orchestrator's task or round:
 * a heading over them. A task's title and note are model output: text only. */
function ScopeHeading({ entry }: { entry: Extract<StepEntry, { kind: "scope" }> }) {
  const quiet = entry.status === "dropped" || entry.status === "pending";
  return (
    <div
      data-testid="step-scope"
      data-key={entry.key}
      data-status={entry.status}
      className={cn("flex min-w-0 flex-col py-1.5 pr-2", indent(entry.depth))}
    >
      <span
        className={cn(
          "flex min-w-0 items-center gap-2 text-caption font-semibold text-foreground-secondary",
          quiet && "text-muted-foreground",
        )}
      >
        <StatusMarker status={entry.status} small />
        <span
          className={cn(
            "shrink-0 truncate font-mono font-medium",
            quiet ? "text-muted-foreground" : "text-foreground",
          )}
        >
          {entry.name}
        </span>
        {entry.itemKind ? (
          <span className="min-w-0 truncate font-medium">{entry.itemKind}</span>
        ) : null}
      </span>
      {entry.note ? (
        <span
          data-testid="step-scope-note"
          className={cn(
            "truncate pl-5 text-caption",
            entry.status === "failed" ? "text-status-failed" : "text-muted-foreground",
          )}
        >
          {entry.note}
        </span>
      ) : null}
    </div>
  );
}

/** Where level `depth`'s status icon is centred, in px from the row's left (its indent + 8). */
function iconX(depth: number): number {
  return 16 + 20 * Math.min(depth, DEPTH.length - 1);
}

/** Whether a later entry at `level` comes before the list leaves the parent at `level - 1`. */
function hasLaterSibling(entries: StepEntry[], index: number, level: number): boolean {
  for (const entry of entries.slice(index + 1)) {
    if (entry.depth < level) return false;
    if (entry.depth === level) return true;
  }
  return false;
}

const GUIDE = "pointer-events-none absolute w-px bg-border-strong";

/**
 * The tree lines of entry `index`, as in a file tree: a line down from each parent's icon to its
 * last child, an elbow into each child's icon, and a line from a row's own icon to its first
 * child. They run 2 px past the row (`-bottom-0.5`) to meet the next row across the list's gap.
 */
function Guides({ entries, index }: { entries: StepEntry[]; index: number }) {
  const entry = entries[index]!;
  const depth = entry.depth;
  // The icon's middle, from the row's top: a step row's (py-2, h-5) or a heading's (py-1.5).
  const iconY = entry.kind === "scope" ? 14 : 18;
  const lines: ReactNode[] = [];
  for (let level = 0; level < depth; level++) {
    const x = iconX(level);
    const continues = hasLaterSibling(entries, index, level + 1);
    if (level === depth - 1) {
      lines.push(
        <span
          key={`v${level}`}
          className={cn(GUIDE, "top-0", continues && "-bottom-0.5")}
          style={{ left: x, height: continues ? undefined : iconY }}
        />,
        <span
          key={`h${level}`}
          className="pointer-events-none absolute h-px bg-border-strong"
          style={{ left: x, top: iconY, width: iconX(depth) - x - 10 }}
        />,
      );
    } else if (continues) {
      lines.push(
        <span key={`v${level}`} className={cn(GUIDE, "top-0 -bottom-0.5")} style={{ left: x }} />,
      );
    }
  }
  const next = entries[index + 1];
  if (next && next.depth > depth) {
    lines.push(
      <span
        key="down"
        className={cn(GUIDE, "-bottom-0.5")}
        style={{ left: iconX(depth), top: iconY + 10 }}
      />,
    );
  }
  return <>{lines}</>;
}

/**
 * The run's steps as a list: status, type, name, one line on what each did, its duration and
 * cost. Map items, branches and iterations nest under their node, joined to it by tree lines.
 * Selecting a row shows the step beside the list.
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
        {entries.map((entry, index) => (
          <li key={`${entry.kind}:${entry.key}`} className="relative min-w-0">
            <Guides entries={entries} index={index} />
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
