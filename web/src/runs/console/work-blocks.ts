import type { MessageTurn, ReasoningTurn, Step, ToolTurn } from "../timeline";
import { describeTool, summarizeTools, toolPreview } from "./tool-describe";

/**
 * An agent's work read the way a chat with Claude reads: each turn is the work it did (its
 * reasoning, notes and tool calls, in order), then its answer. The work folds away; the answer
 * stays. Turns are derived from the order of the step's events, so older runs read the same way.
 */

export type WorkRow =
  /** A call that stands on its own: it has an intent, changes something or failed. */
  | { kind: "tool"; turn: ToolTurn }
  /** Consecutive reads, listings and searches with no intent, folded into one summary row. */
  | { kind: "tools"; turns: ToolTurn[] }
  /** Text the agent wrote between calls. */
  | { kind: "note"; turn: MessageTurn }
  | { kind: "reasoning"; turn: ReasoningTurn };

export interface AgentTurn {
  /** A stable React key: the key of the turn's first row or of its answer. */
  key: number;
  work: WorkRow[];
  /** The turn's answer: its final message, or the text it ends with. `null` while it works,
   * and when the step failed or was cancelled before answering. */
  answer: MessageTurn | null;
}

/** A call shown inside a folded group: quiet (no preview) and with no intent of its own. */
const folds = (turn: ToolTurn) => turn.intent === null && toolPreview(turn) === null;

/** The step's turns: work, then an answer. A step that only answered has no work. */
export function agentTurns(step: Step): AgentTurn[] {
  const out: AgentTurn[] = [];
  let work: WorkRow[] = [];
  const close = (answer: MessageTurn | null) => {
    const key = (work[0] ? rowKey(work[0]) : answer?.key) ?? 0;
    out.push({ key, work, answer });
    work = [];
  };
  step.turns.forEach((turn, i) => {
    if (turn.kind === "message") {
      // Text the agent ends on is its answer, even before the `message` event confirms it;
      // text followed by more work is a note.
      if (turn.final || i === step.turns.length - 1) close(turn);
      else work.push({ kind: "note", turn });
    } else if (turn.kind === "reasoning") {
      work.push({ kind: "reasoning", turn });
    } else {
      const last = work.at(-1);
      if (!folds(turn)) work.push({ kind: "tool", turn });
      else if (last?.kind === "tools") last.turns.push(turn);
      else work.push({ kind: "tools", turns: [turn] });
    }
  });
  if (work.length > 0) close(null);
  return out;
}

function rowKey(row: WorkRow): number {
  return row.kind === "tools" ? row.turns[0]!.key : row.turn.key;
}

export function workTools(work: WorkRow[]): ToolTurn[] {
  return work.flatMap((row) =>
    row.kind === "tools" ? row.turns : row.kind === "tool" ? [row.turn] : [],
  );
}

export function hasFailure(work: WorkRow[]): boolean {
  return workTools(work).some((t) => t.status === "failed");
}

export interface WorkSummary {
  /** What was done: "Listed 3 folders, read 11 files", or "Thought it through" with no calls. */
  text: string;
  toolCalls: number;
  failed: number;
  /** From the block's start to its last call's result; `null` with no finished call. */
  ms: number | null;
}

/** When a block started: the step's start for its first turn, else its first timed row. */
export function workStart(step: Step, turn: AgentTurn, index: number): string {
  if (index === 0) return step.startedAt;
  for (const row of turn.work) {
    if (row.kind === "tools") return row.turns[0]!.startedAt;
    if (row.kind !== "note") return row.turn.startedAt;
  }
  return step.startedAt;
}

export function workSummary(work: WorkRow[], startedAt: string): WorkSummary {
  const tools = workTools(work);
  const ended = tools.flatMap((t) => (t.endedAt ? [Date.parse(t.endedAt)] : []));
  return {
    text: tools.length > 0 ? summarizeTools(tools) : "Thought it through",
    toolCalls: tools.length,
    failed: tools.filter((t) => t.status === "failed").length,
    ms: ended.length > 0 ? Math.max(0, Math.max(...ended) - Date.parse(startedAt)) : null,
  };
}

/** What a live block is doing now: the current call's intent, else what the call does, else
 * "Thinking" (reasoning, or between calls). */
export function currentTitle(work: WorkRow[]): { text: string; target: string } {
  const last = work.at(-1);
  const tool =
    last?.kind === "tool" ? last.turn : last?.kind === "tools" ? last.turns.at(-1) : undefined;
  if (tool?.intent) return { text: tool.intent, target: "" };
  if (tool?.status === "running") {
    const d = describeTool(tool.name, tool.arguments);
    return { text: d.doing, target: d.target };
  }
  return { text: "Thinking", target: "" };
}

/** A map's items added up: how many, their tool calls, and from the first start to the last
 * end (`null` while one runs). */
export function mapTotals(step: Step): { items: number; toolCalls: number; ms: number | null } {
  const items = step.items ?? [];
  let toolCalls = 0;
  const visit = (steps: Step[]) => {
    for (const s of steps) {
      toolCalls += s.turns.filter((t) => t.kind === "tool").length;
      for (const item of s.items ?? []) visit(item.steps);
      for (const branch of s.branches ?? []) visit(branch.steps);
      for (const iteration of s.iterations ?? []) visit(iteration.steps);
    }
  };
  for (const item of items) visit(item.steps);
  const starts = items.map((i) => Date.parse(i.startedAt));
  const ends = items.map((i) => (i.endedAt ? Date.parse(i.endedAt) : null));
  const ms =
    starts.length > 0 && ends.every((e) => e !== null)
      ? Math.max(...(ends as number[])) - Math.min(...starts)
      : null;
  return { items: items.length, toolCalls, ms };
}
