"use client";

import { ChevronRightIcon, WrenchIcon } from "lucide-react";

import { JsonView, OutputView } from "@/components/json-view";
import { StatusBadge } from "@/components/status-badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

import { formatDuration } from "../summaries";
import type { ToolTurn } from "../timeline";
import { stepBadge } from "./step-status";

/** A tool call and its result, collapsed to one line until opened. */
export function ToolCard({ turn }: { turn: ToolTurn }) {
  const badge = stepBadge(turn.status);
  const took = turn.endedAt !== null ? Date.parse(turn.endedAt) - Date.parse(turn.startedAt) : null;
  return (
    <Collapsible
      data-testid="tool-card"
      data-status={turn.status}
      className="group/tool rounded-lg border bg-card text-[13px]"
    >
      <CollapsibleTrigger className="flex w-full min-w-0 items-center gap-2 rounded-lg px-3 py-2 text-left outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50">
        <ChevronRightIcon
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground group-data-[state=open]/tool:rotate-90 motion-safe:transition-transform"
        />
        <WrenchIcon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 truncate font-mono">{turn.name}</span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          {took !== null ? (
            <span className="text-muted-foreground tabular-nums">{formatDuration(took)}</span>
          ) : null}
          <StatusBadge status={badge.status} label={badge.label} />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-3 border-t px-3 py-3">
        <section className="flex flex-col gap-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Arguments</h4>
          <JsonView value={turn.arguments} label={`${turn.name} arguments`} />
        </section>
        <section className="flex flex-col gap-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Result</h4>
          {turn.output === null ? (
            <p className="text-muted-foreground">Waiting for the result…</p>
          ) : (
            <OutputView text={turn.output} label={`${turn.name} result`} />
          )}
        </section>
      </CollapsibleContent>
    </Collapsible>
  );
}
