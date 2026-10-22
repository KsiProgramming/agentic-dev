"use client";

import { ChevronRightIcon, CircleXIcon, LoaderCircleIcon } from "lucide-react";

import { JsonView, OutputView } from "@/components/json-view";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

import { formatDuration } from "../summaries";
import type { ToolTurn } from "../timeline";
import { describeTool, summarizeTools } from "./tool-describe";

function took(turn: ToolTurn): number | null {
  return turn.endedAt !== null ? Date.parse(turn.endedAt) - Date.parse(turn.startedAt) : null;
}

const TRIGGER =
  "flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] text-muted-foreground outline-none hover:bg-muted/60 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50";

/** Class names are written out in full so Tailwind sees them. */
const CHEVRON = {
  call: "group-data-[state=open]/call:rotate-90",
  group: "group-data-[state=open]/group:rotate-90",
};

function Chevron({ of }: { of: keyof typeof CHEVRON }) {
  return (
    <ChevronRightIcon
      aria-hidden="true"
      className={`size-3.5 shrink-0 opacity-60 motion-safe:transition-transform ${CHEVRON[of]}`}
    />
  );
}

/** One tool call as one quiet line ("Read `src/app.ts`"); opening it shows its arguments and
 * result. Only a call in flight or one that failed gets a status icon. */
export function ToolCallRow({ turn }: { turn: ToolTurn }) {
  const d = describeTool(turn.name, turn.arguments);
  const ms = took(turn);
  const Icon =
    turn.status === "running" ? LoaderCircleIcon : turn.status === "failed" ? CircleXIcon : d.icon;
  return (
    <li data-testid="tool-call" data-status={turn.status} className="min-w-0">
      <Collapsible className="group/call">
        <CollapsibleTrigger className={TRIGGER}>
          <Icon
            aria-hidden="true"
            className={
              turn.status === "running"
                ? "size-3.5 shrink-0 text-status-running motion-safe:animate-spin"
                : turn.status === "failed"
                  ? "size-3.5 shrink-0 text-status-failed"
                  : "size-3.5 shrink-0"
            }
          />
          {/* The spaces between the spans keep the button's accessible name readable. */}
          <span className="shrink-0">{turn.status === "running" ? d.doing : d.done}</span>{" "}
          {d.target ? (
            <span className="min-w-0 truncate font-mono text-foreground">{d.target}</span>
          ) : null}{" "}
          {turn.status === "failed" ? (
            <span className="shrink-0 text-status-failed">failed</span>
          ) : null}{" "}
          <span className="ml-auto flex shrink-0 items-center gap-1.5">
            {ms !== null ? (
              <span className="text-xs tabular-nums">{formatDuration(ms)}</span>
            ) : null}
            <Chevron of="call" />
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-1 mb-2 ml-3.5 flex flex-col gap-2 border-l pl-4">
          <section className="flex flex-col gap-1">
            <h4 className="text-xs font-medium text-muted-foreground">Arguments</h4>
            <JsonView value={turn.arguments} label={`${turn.name} arguments`} />
          </section>
          <section className="flex flex-col gap-1">
            <h4 className="text-xs font-medium text-muted-foreground">Result</h4>
            {turn.output === null ? (
              <p className="text-[13px] text-muted-foreground">Waiting for the result…</p>
            ) : (
              <OutputView text={turn.output} label={`${turn.name} result`} />
            )}
          </section>
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

/**
 * Consecutive tool calls of one agent turn, collapsed to one summary line ("Read 9 files,
 * listed 2 folders"). While a call is in flight the line says what the agent is doing. A single
 * call is shown as its own line.
 */
export function ToolCallGroup({ turns }: { turns: ToolTurn[] }) {
  if (turns.length === 1) {
    return (
      <ul data-testid="tool-group" className="flex flex-col">
        <ToolCallRow turn={turns[0]!} />
      </ul>
    );
  }
  const running = turns.findLast((t) => t.status === "running");
  const failed = turns.filter((t) => t.status === "failed").length;
  const first = turns[0]!;
  const last = turns[turns.length - 1]!;
  const ms =
    running || last.endedAt === null
      ? null
      : Date.parse(last.endedAt) - Date.parse(first.startedAt);
  const current = running ? describeTool(running.name, running.arguments) : null;

  return (
    <Collapsible data-testid="tool-group" className="group/group min-w-0">
      <CollapsibleTrigger className={TRIGGER}>
        {current ? (
          <LoaderCircleIcon
            aria-hidden="true"
            className="size-3.5 shrink-0 text-status-running motion-safe:animate-spin"
          />
        ) : (
          <Chevron of="group" />
        )}
        <span className="min-w-0 truncate">
          {current ? (
            <>
              {current.doing}{" "}
              {current.target ? (
                <span className="font-mono text-foreground">{current.target}</span>
              ) : null}
              …
            </>
          ) : (
            summarizeTools(turns)
          )}
        </span>{" "}
        {failed > 0 ? <span className="shrink-0 text-status-failed">· {failed} failed</span> : null}{" "}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs tabular-nums">
          {turns.length} tool calls{ms !== null ? ` · ${formatDuration(ms)}` : ""}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-0.5 ml-3.5 flex flex-col border-l pl-2">
          {turns.map((turn) => (
            <ToolCallRow key={turn.key} turn={turn} />
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
