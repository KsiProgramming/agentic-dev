"use client";

import { CircleAlertIcon } from "lucide-react";

import type { MessageTurn, Step, ToolTurn, Turn } from "../timeline";
import { AgentMessage } from "./agent-message";
import { DotMarker, Rail, RailItem, StatusMarker } from "./rail";
import { ToolCallGroup } from "./tool-calls";
import { toolPreview } from "./tool-describe";

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

export function ErrorLine({ error }: { error: string }) {
  return (
    <p className="flex items-start gap-1.5 text-meta break-words text-destructive">
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </p>
  );
}

/** What an agent did, in order, on a rail: its messages and tool calls. */
export function TurnsRail({ step }: { step: Step }) {
  const live = step.status === "running";
  return (
    <Rail>
      {segments(step.turns).map((segment) =>
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
    </Rail>
  );
}
