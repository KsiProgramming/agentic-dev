import type { components } from "@/api/schema";

/** One row of a run's event log, as streamed by `GET /runs/{id}/events`. */
export type RunEvent = components["schemas"]["RunEvent"];

/** A run event plus when this browser received it (ms since epoch). */
export type ReceivedRunEvent = RunEvent & { receivedAt: number };

/** How a run ended, keyed by its final event type. */
export const RUN_END_STATUS = {
  run_completed: "completed",
  run_failed: "failed",
  run_cancelled: "cancelled",
} as const;

export type RunOutcome = (typeof RUN_END_STATUS)[keyof typeof RUN_END_STATUS];

export type StreamStatus = "connecting" | "live" | RunOutcome | "not_found" | "error";

/**
 * Every `event:` name the stream sends: engine lifecycle events and agent events. `EventSource`
 * only delivers named events to listeners registered for that name.
 */
export const EVENT_TYPES = [
  "run_started",
  "run_resumed",
  "run_completed",
  "run_failed",
  "run_cancelled",
  "node_started",
  "node_completed",
  "node_failed",
  "node_cancelled",
  "gate_waiting",
  "gate_decided",
  "loop_iteration_started",
  "loop_condition_evaluated",
  "map_item_started",
  "map_item_completed",
  "parallel_branch_started",
  "parallel_branch_completed",
  "pr_opened",
  "repo_created",
  "policy_limit_exceeded",
  "text_delta",
  "message",
  "tool_call",
  "tool_result",
  "usage",
  "completed",
  "failed",
  "cancelled",
] as const;

export function runOutcome(type: string): RunOutcome | undefined {
  return Object.hasOwn(RUN_END_STATUS, type)
    ? RUN_END_STATUS[type as keyof typeof RUN_END_STATUS]
    : undefined;
}
