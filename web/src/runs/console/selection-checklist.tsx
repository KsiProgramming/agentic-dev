"use client";

import { ListChecksIcon } from "lucide-react";
import { useId } from "react";

import { TruncatedPath } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

import { useRunArtifact } from "../artifacts/use-run-artifacts";
import { Message, SeverityBadge } from "../findings/findings-view";
import { isFindingsReport, location, type Finding } from "../findings/findings";
import type { GateSelection } from "../gates";
import type { GateChoice } from "./use-gate-decision";

/** One item a selection gate shows: its key (null when it cannot be chosen), and the finding it
 * is when the artifact is a findings report. */
export interface ChoiceItem {
  key: string | null;
  finding: Finding | null;
  /** A one-line summary for an item that is not a finding: data, shown as text. */
  summary: string;
}

/** The key of `item` under `key`, as the engine reads it (`item_key`): a non-empty string or an
 * integer, as text. */
function keyOf(item: unknown, key: string): string | null {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null;
  const value = (item as Record<string, unknown>)[key];
  if (typeof value === "string") return value || null;
  if (typeof value === "number" && Number.isInteger(value)) return String(value);
  return null;
}

function summaryOf(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object" && !Array.isArray(item)) {
    const fields = item as Record<string, unknown>;
    for (const name of ["title", "message", "name", "description"]) {
      if (typeof fields[name] === "string") return fields[name];
    }
  }
  return JSON.stringify(item);
}

/**
 * The items of a selection gate's artifact `content` (6.7), in its order: only those whose key
 * the gate listed can be chosen (an item with no key, or a key an earlier item has, cannot).
 * Null when the content is not JSON or has no list under `select.items`.
 */
export function choiceItems(select: GateSelection, content: string): ChoiceItem[] | null {
  let document: unknown;
  try {
    document = JSON.parse(content);
  } catch {
    return null;
  }
  if (!document || typeof document !== "object" || Array.isArray(document)) return null;
  const items = (document as Record<string, unknown>)[select.items];
  if (!Array.isArray(items)) return null;
  const findings = isFindingsReport(document) && select.items === "findings";
  const listed = new Set(select.keys);
  const seen = new Set<string>();
  return items.map((item: unknown): ChoiceItem => {
    const found = keyOf(item, select.key);
    const key = found !== null && listed.has(found) && !seen.has(found) ? found : null;
    if (key !== null) seen.add(key);
    return { key, finding: findings ? (item as Finding) : null, summary: summaryOf(item) };
  });
}

/**
 * A selection gate's checklist (tech-stack → Approval dock, Inbox): the artifact's items, a
 * checkbox each, with "Select all", "Clear" and "N of M selected". A finding reads as in the
 * Findings view (severity, rule, `path:line`, message; the rule as text, as a link inside the
 * row's label would toggle it); any other item as its key and a line.
 * Items are data: text only. Loading, empty and error states come from `@/components/states`.
 */
export function SelectionChecklist({
  runId,
  choice,
  baseUrl,
}: {
  runId: string;
  choice: GateChoice;
  baseUrl?: string;
}) {
  const { select } = choice;
  const headingId = useId();
  const artifact = useRunArtifact(runId, select.artifact, select.version, { baseUrl });
  if (artifact.isPending) return <LoadingState rows={4} label="Loading the items…" />;
  if (!artifact.data) {
    return (
      <ErrorState
        message={artifact.error?.message ?? `Could not load ${select.artifact}.`}
        onRetry={() => void artifact.refetch()}
      />
    );
  }
  const items = choiceItems(select, artifact.data.content);
  if (items === null) {
    return <ErrorState message={`${select.artifact} has no list of items to choose from.`} />;
  }
  if (items.length === 0) {
    return <EmptyState icon={ListChecksIcon} message="The artifact has no items." />;
  }
  const choosable = items.filter((i) => i.key !== null).length;
  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="text-caption font-medium text-muted-foreground">
          {select.items === "findings" ? "Findings" : "Items"}
        </h3>
        <p className="text-meta text-foreground-secondary" aria-live="polite">
          {choice.count} of {choosable} selected
        </p>
        <div className="ml-auto flex gap-1">
          <Button type="button" variant="ghost" size="sm" onClick={choice.all}>
            Select all
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={choice.clear}>
            Clear
          </Button>
        </div>
      </div>
      <ul
        aria-labelledby={headingId}
        data-testid="selection-checklist"
        className="flex flex-col divide-y divide-divider rounded-lg border"
      >
        {items.map((item, index) => (
          <ChecklistRow key={item.key ?? `item-${index}`} item={item} choice={choice} />
        ))}
      </ul>
    </section>
  );
}

function ChecklistRow({ item, choice }: { item: ChoiceItem; choice: GateChoice }) {
  const id = useId();
  const { key, finding } = item;
  const checked = key !== null && choice.chosen.has(key);
  return (
    <li
      data-testid="selection-item"
      data-selected={checked || undefined}
      className="flex min-w-0 items-start gap-3 px-3 py-2 text-meta data-selected:bg-surface-subtle"
    >
      <Checkbox
        id={id}
        className="mt-0.5"
        checked={checked}
        disabled={key === null}
        onCheckedChange={(on) => key !== null && choice.toggle(key, on === true)}
        aria-describedby={key === null ? `${id}-why` : undefined}
      />
      <label htmlFor={id} className="flex min-w-0 flex-1 flex-col gap-1">
        {finding ? (
          <>
            <span className="flex min-w-0 flex-wrap items-center gap-2">
              <SeverityBadge severity={finding.severity} />
              <span className="font-mono text-caption">{finding.rule}</span>
              <TruncatedPath
                path={location(finding)}
                focusable={false}
                className="min-w-0 text-foreground-secondary"
              />
            </span>
            <span className="text-foreground">
              <Message finding={finding} />
            </span>
          </>
        ) : (
          <>
            {key !== null ? <span className="font-mono text-caption">{key}</span> : null}
            <span className="truncate" title={item.summary}>
              {item.summary}
            </span>
          </>
        )}
        {key === null ? (
          <span id={`${id}-why`} className="text-caption text-muted-foreground">
            Cannot be chosen: it has no key of its own.
          </span>
        ) : null}
      </label>
    </li>
  );
}
