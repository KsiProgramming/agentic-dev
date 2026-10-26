import { addUsage, usageOfEvent, type TokenUsage } from "./cost";
import { parseChanges, parseEdits, type FileChange, type FileEdit } from "./gates";
import type { RunEvent } from "./types";

export type { TokenUsage } from "./cost";

/**
 * The run as a story: one step per node in run order, map items and loop iterations nested
 * inside their node, and inside each step its turns. Streamed `text_delta` chunks are merged into
 * one growing message per agent turn; a tool call and its result form one tool turn. Payloads are
 * data: nothing here is ever rendered as HTML.
 */

export type StepStatus = "running" | "waiting" | "completed" | "failed" | "cancelled";

export interface MessageTurn {
  kind: "message";
  /** The `seq` of the event that opened the turn: a stable React key. */
  key: number;
  /** The chunks joined in order, or the final `message` text once it arrived. */
  text: string;
  /** The `message` event replaced the merged chunks: the turn will not grow any more. */
  final: boolean;
  /** How many `text_delta` events the turn merged. */
  chunks: number;
}

export interface ToolTurn {
  kind: "tool";
  key: number;
  callId: string;
  name: string;
  arguments: unknown;
  /** The tool's output, once its result arrived. */
  output: string | null;
  status: "running" | "completed" | "failed";
  startedAt: string;
  endedAt: string | null;
}

export type Turn = MessageTurn | ToolTurn;

export interface GateInfo {
  title: string;
  decision: string | null;
  comment: string | null;
  /** The files the writers before the gate changed, as it showed them. */
  changes: FileChange[];
  /** The approver's edits to them, once decided. */
  edits: FileEdit[];
}

export interface Step {
  /** The node id. */
  id: string;
  status: StepStatus;
  startedAt: string;
  endedAt: string | null;
  error: string | null;
  turns: Turn[];
  /** The node's own usage; `stepUsage` adds its map items and iterations. */
  usage: TokenUsage | null;
  gate: GateInfo | null;
  prUrl: string | null;
  /** Set for a loop node: one entry per iteration, each with its own steps. */
  iterations: Iteration[] | null;
  /** Set for a map node: one entry per item, each with its own steps. */
  items: MapItem[] | null;
  /** How many items a map node has, once it started. */
  itemCount: number | null;
  /** Why a loop stopped: `condition` or `max_iterations`. */
  stopReason: string | null;
}

export interface Iteration {
  index: number;
  steps: Step[];
  /** The `until` condition's result after this iteration, once evaluated. */
  conditionMet: boolean | null;
}

export interface MapItem {
  index: number;
  item: unknown;
  status: StepStatus;
  startedAt: string;
  endedAt: string | null;
  error: string | null;
  steps: Step[];
}

export interface Timeline {
  steps: Step[];
  workflowName: string | null;
  startedAt: string | null;
  endedAt: string | null;
}

const END_STATUS: Record<string, StepStatus> = {
  node_completed: "completed",
  node_failed: "failed",
  node_cancelled: "cancelled",
};

const RUN_END: Record<string, StepStatus> = {
  run_completed: "completed",
  run_failed: "failed",
  run_cancelled: "cancelled",
};

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function newStep(id: string, at: string): Step {
  return {
    id,
    status: "running",
    startedAt: at,
    endedAt: null,
    error: null,
    turns: [],
    usage: null,
    gate: null,
    prUrl: null,
    iterations: null,
    items: null,
    itemCount: null,
    stopReason: null,
  };
}

/** A GitHub pull request URL; anything else (e.g. a `javascript:` URL) is not offered as a link. */
export function safePullRequestUrl(url: unknown): string | null {
  if (typeof url !== "string") return null;
  return /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+$/.test(url) ? url : null;
}

/** Where the events of one level go: the run's top level, a loop iteration or a map item. */
interface Scope {
  steps: Step[];
}

class Builder {
  readonly timeline: Timeline = { steps: [], workflowName: null, startedAt: null, endedAt: null };
  /** The loops and maps that have started and not ended yet, innermost last. */
  private open: Step[] = [];
  private seen = new Set<number>();

  add(event: RunEvent) {
    if (this.seen.has(event.seq)) return;
    this.seen.add(event.seq);
    const payload = event.payload ?? {};
    const at = event.created_at;

    switch (event.type) {
      case "run_started":
        this.timeline.workflowName = str(payload.workflow_name);
        this.timeline.startedAt ??= at;
        return;
      case "run_completed":
      case "run_failed":
      case "run_cancelled":
        this.timeline.endedAt = at;
        this.endUnfinished(RUN_END[event.type] ?? "cancelled", at);
        return;
    }

    const nodeId = event.node_id;
    if (!nodeId) return;
    const item = num(payload.item);

    // Events a loop or map writes about itself.
    switch (event.type) {
      case "loop_iteration_started": {
        const loop = this.container(nodeId, at);
        loop.iterations ??= [];
        loop.iterations.push({
          index: num(payload.iteration) ?? loop.iterations.length + 1,
          steps: [],
          conditionMet: null,
        });
        return;
      }
      case "loop_condition_evaluated": {
        const loop = this.container(nodeId, at);
        const iteration = loop.iterations?.at(-1);
        if (iteration && typeof payload.result === "boolean")
          iteration.conditionMet = payload.result;
        return;
      }
      case "map_item_started": {
        const map = this.container(nodeId, at);
        map.items ??= [];
        const index = num(payload.index) ?? map.items.length;
        const existing = map.items.find((i) => i.index === index);
        if (existing) {
          existing.status = "running";
          existing.endedAt = null;
        } else {
          map.items.push({
            index,
            item: payload.item,
            status: "running",
            startedAt: at,
            endedAt: null,
            error: null,
            steps: [],
          });
          map.items.sort((a, b) => a.index - b.index);
        }
        return;
      }
      case "map_item_completed": {
        const map = this.container(nodeId, at);
        const entry = map.items?.find((i) => i.index === num(payload.index));
        if (entry) {
          entry.status = (str(payload.status) as StepStatus | null) ?? "completed";
          entry.endedAt = at;
          entry.error = str(payload.error);
        }
        return;
      }
    }

    const scope = this.scopeFor(nodeId, item);
    let step = scope.steps.find((s) => s.id === nodeId);

    if (event.type === "node_started") {
      if (step) {
        // A node cut off by a worker restart runs again; a gate is announced again.
        step.status = "running";
        step.endedAt = null;
      } else {
        step = newStep(nodeId, at);
        scope.steps.push(step);
      }
      if (payload.items !== undefined) {
        step.items ??= [];
        step.itemCount = num(payload.items);
      }
      return;
    }

    step ??= (() => {
      const created = newStep(nodeId, at);
      scope.steps.push(created);
      return created;
    })();

    switch (event.type) {
      case "node_completed":
      case "node_failed":
      case "node_cancelled":
        step.status = END_STATUS[event.type] ?? "completed";
        step.endedAt = at;
        step.error = str(payload.error) ?? step.error;
        step.stopReason = str(payload.stop_reason);
        this.open = this.open.filter((s) => s !== step);
        return;
      case "gate_waiting":
        step.status = "waiting";
        step.gate = {
          title: str(payload.title) ?? "Approve?",
          decision: null,
          comment: null,
          changes: parseChanges(payload.changes),
          edits: [],
        };
        return;
      case "gate_decided":
        step.status = "running";
        step.gate = {
          title: step.gate?.title ?? "Approve?",
          decision: str(payload.decision),
          comment: str(payload.comment),
          changes: step.gate?.changes ?? [],
          edits: parseEdits(payload.edits),
        };
        return;
      case "pr_opened":
        step.prUrl = safePullRequestUrl(payload.url);
        return;
      case "text_delta": {
        const last = step.turns.at(-1);
        const text = str(payload.text) ?? "";
        if (last?.kind === "message" && !last.final) {
          last.text += text;
          last.chunks += 1;
        } else {
          step.turns.push({ kind: "message", key: event.seq, text, final: false, chunks: 1 });
        }
        return;
      }
      case "message": {
        const last = step.turns.at(-1);
        const text = str(payload.text) ?? "";
        if (last?.kind === "message" && !last.final) {
          last.text = text;
          last.final = true;
        } else if (text) {
          step.turns.push({ kind: "message", key: event.seq, text, final: true, chunks: 0 });
        }
        return;
      }
      case "tool_call":
        step.turns.push({
          kind: "tool",
          key: event.seq,
          callId: str(payload.call_id) ?? String(event.seq),
          name: str(payload.name) ?? "tool",
          arguments: payload.arguments ?? {},
          output: null,
          status: "running",
          startedAt: at,
          endedAt: null,
        });
        return;
      case "tool_result": {
        const callId = str(payload.call_id);
        const call = step.turns.findLast(
          (t): t is ToolTurn => t.kind === "tool" && t.callId === callId,
        );
        if (!call) return;
        call.output = str(payload.output) ?? "";
        call.status = payload.is_error === true ? "failed" : "completed";
        call.endedAt = at;
        return;
      }
      case "usage":
        step.usage = addUsage(step.usage, usageOfEvent(payload));
        return;
      case "failed":
        step.error = str(payload.error) ?? step.error;
        return;
    }
  }

  /** The loop or map `nodeId` at the current level, opened if it is not open yet. */
  private container(nodeId: string, at: string): Step {
    const open = this.open.find((s) => s.id === nodeId);
    if (open) return open;
    const scope = this.scopeFor(nodeId, null);
    let step = scope.steps.find((s) => s.id === nodeId);
    if (!step) {
      step = newStep(nodeId, at);
      scope.steps.push(step);
    }
    this.open.push(step);
    return step;
  }

  /**
   * Where a node's events go. Events tagged with a map `item` go to that item of the innermost
   * open map; others go to the current iteration of the innermost open loop, or the top level.
   */
  private scopeFor(nodeId: string, item: number | null): Scope {
    for (let i = this.open.length - 1; i >= 0; i--) {
      const container = this.open[i]!;
      if (container.id === nodeId) continue;
      if (item !== null && container.items) {
        const entry = container.items.find((e) => e.index === item);
        if (entry) return entry;
        continue;
      }
      if (item === null && container.iterations) {
        const iteration = container.iterations.at(-1);
        if (iteration) return iteration;
      }
    }
    return this.timeline;
  }

  /** The run ended: steps cut off without their own end take its status. */
  private endUnfinished(status: StepStatus, at: string) {
    const visit = (steps: Step[]) => {
      for (const step of steps) {
        if (step.status === "running" || step.status === "waiting") {
          step.status = status;
          step.endedAt ??= at;
        }
        for (const iteration of step.iterations ?? []) visit(iteration.steps);
        for (const entry of step.items ?? []) {
          if (entry.status === "running") {
            entry.status = status;
            entry.endedAt ??= at;
          }
          visit(entry.steps);
        }
      }
    };
    visit(this.timeline.steps);
    this.open = [];
  }
}

/** The timeline of a run's events, given in `seq` order. Duplicate `seq`s are ignored. */
export function buildTimeline(events: readonly RunEvent[]): Timeline {
  const builder = new Builder();
  for (const event of events) builder.add(event);
  return builder.timeline;
}

/** One row of the Raw events tab: an event, or consecutive chunks of one message folded. */
export type RawRow<E extends RunEvent = RunEvent> =
  | { kind: "event"; event: E }
  | {
      kind: "text";
      /** The chunks, in order. */
      events: [E, ...E[]];
      /** The chunks joined: the message as it was streamed. */
      text: string;
      nodeId: string | null;
      item: number | null;
    };

/**
 * Fold consecutive `text_delta` events of the same node and map item into one row, so a
 * streamed message reads as one paragraph rather than one row per chunk. Any other event, or a
 * chunk of another node or item, ends the fold.
 */
export function foldDeltas<E extends RunEvent>(events: readonly E[]): RawRow<E>[] {
  const rows: RawRow<E>[] = [];
  for (const event of events) {
    const last = rows.at(-1);
    if (event.type !== "text_delta") {
      rows.push({ kind: "event", event });
      continue;
    }
    const item = num(event.payload?.item);
    const text = str(event.payload?.text) ?? "";
    if (last?.kind === "text" && last.nodeId === (event.node_id ?? null) && last.item === item) {
      last.events.push(event);
      last.text += text;
    } else {
      rows.push({ kind: "text", events: [event], text, nodeId: event.node_id ?? null, item });
    }
  }
  return rows;
}

/** A step's usage with that of its map items and loop iterations: what the node cost. */
export function stepUsage(step: Step): TokenUsage | null {
  let total = step.usage;
  for (const item of step.items ?? []) total = addUsage(total, stepsUsage(item.steps));
  for (const iteration of step.iterations ?? []) {
    total = addUsage(total, stepsUsage(iteration.steps));
  }
  return total;
}

/** The usage of `steps` and everything nested in them; for the run, its timeline's steps. */
export function stepsUsage(steps: Step[]): TokenUsage | null {
  return steps.reduce<TokenUsage | null>((total, step) => addUsage(total, stepUsage(step)), null);
}
