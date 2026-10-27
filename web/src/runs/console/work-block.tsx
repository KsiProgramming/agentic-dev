"use client";

import { BrainIcon, ChevronRightIcon, LoaderCircleIcon } from "lucide-react";
import { useState } from "react";

import { Duration } from "@/components/display";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

import type { ReasoningTurn, Step, ToolTurn } from "../timeline";
import { useNow } from "../use-now";
import { AgentMessage } from "./agent-message";
import { DotMarker, IconMarker, Rail, RailItem, StatusMarker } from "./rail";
import { ToolCallGroup } from "./tool-calls";
import {
  agentTurns,
  currentTitle,
  hasFailure,
  workStart,
  workSummary,
  type AgentTurn,
  type WorkRow,
} from "./work-blocks";

const HEADER =
  "flex w-full min-w-0 items-center gap-2 rounded-md border bg-muted/30 px-2.5 py-1.5 text-left text-meta text-muted-foreground outline-none hover:bg-muted/60 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50";

/** The marker of a tool row: a spinner while a call runs, a cross if one failed, a dot. */
function ToolsMarker({ turns }: { turns: ToolTurn[] }) {
  if (turns.some((t) => t.status === "running")) return <StatusMarker status="running" small />;
  if (turns.some((t) => t.status === "failed")) return <StatusMarker status="failed" small />;
  return <DotMarker className="bg-status-succeeded" />;
}

/** The model's reasoning: its first line in muted italic, the rest on expand. Plain text: it is
 * agent output, never Markdown or HTML. */
function ReasoningRow({ turn }: { turn: ReasoningTurn }) {
  const text = turn.text.trim();
  const [first = "", ...rest] = text.split("\n");
  const more = rest.join("\n").trim();
  if (!more) {
    return (
      <p
        data-testid="reasoning"
        className="px-1.5 py-1 text-meta break-words text-muted-foreground italic"
      >
        {first}
      </p>
    );
  }
  return (
    <Collapsible data-testid="reasoning" className="group/reasoning min-w-0">
      <CollapsibleTrigger className="flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-1 text-left text-meta text-muted-foreground italic outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50">
        <span className="min-w-0 truncate">{first}</span>
        <ChevronRightIcon
          aria-hidden="true"
          className="ml-auto size-3.5 shrink-0 opacity-60 group-data-[state=open]/reasoning:rotate-90 motion-safe:transition-transform"
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="px-1.5 pb-1 text-meta break-words whitespace-pre-wrap text-muted-foreground italic">
          {more}
        </p>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Row({ row }: { row: WorkRow }) {
  switch (row.kind) {
    case "note":
      return (
        <RailItem marker={<DotMarker />}>
          <AgentMessage text={row.turn.text} className="text-meta text-muted-foreground" />
        </RailItem>
      );
    case "reasoning":
      return (
        <RailItem
          marker={<IconMarker icon={BrainIcon} />}
          className="pl-5.5"
          markerClassName="top-1"
        >
          <ReasoningRow turn={row.turn} />
        </RailItem>
      );
    default: {
      const turns = row.kind === "tools" ? row.turns : [row.turn];
      return (
        <RailItem
          marker={<ToolsMarker turns={turns} />}
          // Tool lines have their own padding: line the marker up with their text.
          markerClassName="top-1"
          className="pl-5.5"
        >
          <ToolCallGroup turns={turns} />
        </RailItem>
      );
    }
  }
}

function rowKey(row: WorkRow): number {
  return row.kind === "tools" ? row.turns[0]!.key : row.turn.key;
}

/** The ticking time of a live block. Not announced: the live line says what changes. */
function Elapsed({ since }: { since: string }) {
  const now = useNow(1000);
  return (
    <Duration
      aria-hidden="true"
      data-testid="work-elapsed"
      ms={Math.max(0, now - Date.parse(since))}
      className="text-xs"
    />
  );
}

/**
 * One agent turn's work, folded into one line. While live, the line says what the agent is doing,
 * with a timer, and the block is open; once done it sums up what was done and closes, unless a
 * call failed. Opening and closing it is the user's from then on.
 */
export function WorkBlock({
  turn,
  startedAt,
  live,
}: {
  turn: AgentTurn;
  startedAt: string;
  live: boolean;
}) {
  const [chosen, setChosen] = useState<boolean | null>(null);
  const failed = hasFailure(turn.work);
  const open = chosen ?? (live || failed);
  const summary = workSummary(turn.work, startedAt);
  const current = live ? currentTitle(turn.work) : null;
  const count = `${summary.toolCalls} tool ${summary.toolCalls === 1 ? "call" : "calls"}`;

  return (
    <Collapsible
      data-testid="work-block"
      data-live={live || undefined}
      open={open}
      onOpenChange={setChosen}
      className="group/work flex min-w-0 flex-col gap-2"
    >
      <CollapsibleTrigger className={HEADER}>
        {current ? (
          <LoaderCircleIcon
            aria-hidden="true"
            className="size-3.5 shrink-0 text-status-running motion-safe:animate-spin"
          />
        ) : (
          <ChevronRightIcon
            aria-hidden="true"
            className="size-3.5 shrink-0 opacity-60 group-data-[state=open]/work:rotate-90 motion-safe:transition-transform"
          />
        )}
        <span data-testid="work-title" className="min-w-0 truncate text-foreground">
          {current ? (
            <>
              {current.text}
              {current.target ? (
                <>
                  {" "}
                  <span className="font-mono">{current.target}</span>
                </>
              ) : null}
              …
            </>
          ) : (
            summary.text
          )}
        </span>{" "}
        {summary.failed > 0 ? (
          <span className="shrink-0 text-status-failed">· {summary.failed} failed</span>
        ) : null}{" "}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs tabular-nums">
          {current ? (
            <Elapsed since={startedAt} />
          ) : (
            <>
              {summary.toolCalls > 0 ? count : null}
              {summary.ms !== null ? (
                <>
                  {" "}
                  · <Duration ms={summary.ms} />
                </>
              ) : null}
            </>
          )}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <Rail className="pl-1">
          {turn.work.map((row) => (
            <Row key={rowKey(row)} row={row} />
          ))}
        </Rail>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** An agent step's turns, read like a chat: each turn's work folded, then its answer, open. */
export function AgentTurns({ step, answers = true }: { step: Step; answers?: boolean }) {
  const turns = agentTurns(step);
  const running = step.status === "running";
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {turns.map((turn, i) => {
        const last = i === turns.length - 1;
        return (
          <div key={turn.key} data-testid="agent-turn" className="flex min-w-0 flex-col gap-3">
            {turn.work.length > 0 ? (
              <WorkBlock
                turn={turn}
                startedAt={workStart(step, turn, i)}
                live={running && last && turn.answer === null}
              />
            ) : null}
            {answers && turn.answer?.text.trim() ? (
              <AgentMessage
                text={turn.answer.text}
                streaming={running && last && !turn.answer.final}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
