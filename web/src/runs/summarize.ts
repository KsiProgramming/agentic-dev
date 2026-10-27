import { formatUsd } from "./cost";
import type { RunEvent } from "./types";

const MAX_LENGTH = 200;

function truncate(text: string): string {
  return text.length > MAX_LENGTH ? `${text.slice(0, MAX_LENGTH - 1)}…` : text;
}

function str(value: unknown): string {
  if (value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

const LIMIT_LABELS: Record<string, string> = {
  agents_alive: "agents alive",
  agents_spawned: "agents spawned",
  max_depth: "nesting depth",
  loop_iterations: "loop iterations",
  wall_time_s: "wall time",
  budget_usd: "budget",
};

/** A USD amount of the event, a decimal string ("1.2"). */
function usd(value: unknown): string {
  const n = typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(n) ? formatUsd(n) : str(value);
}

/** "agents spawned: 41, limit 40", "wall time: limit 2h 0m" or "budget: $1.20 spent, limit $1.00". */
function policyLimit(payload: Record<string, unknown>): string {
  const limit = str(payload.limit);
  const label = LIMIT_LABELS[limit] ?? limit;
  const { value, observed } = payload;
  if (limit === "wall_time_s" && typeof value === "number") {
    return `${label}: limit ${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
  }
  if (limit === "budget_usd") {
    const spent = payload.model ? `no price for ${str(payload.model)}` : `${usd(observed)} spent`;
    return `${label}: ${spent}, limit ${usd(value)}`;
  }
  return `${label}: ${str(observed)}, limit ${str(value)}`;
}

/** A one-line, plain-text summary of an event's payload. Payloads are data: never render as HTML. */
export function summarizePayload(event: RunEvent): string {
  const payload = event.payload ?? {};
  switch (event.type) {
    case "text_delta":
    case "message":
      return truncate(str(payload.text));
    case "usage": {
      const tokens = `${str(payload.input_tokens)} in / ${str(payload.output_tokens)} out tokens`;
      const usd = payload.estimated_usd;
      return typeof usd === "number" ? `${tokens}, ~$${usd.toFixed(4)}` : tokens;
    }
    case "run_failed":
    case "node_failed":
    case "failed":
      return truncate(str(payload.error));
    case "tool_call":
      return truncate(`${str(payload.name)}(${JSON.stringify(payload.arguments ?? {})})`);
    case "tool_result":
      return truncate(str(payload.output));
    case "gate_waiting":
      return truncate(str(payload.title));
    case "gate_decided":
      return truncate(
        [str(payload.decision), str(payload.comment ?? "")].filter(Boolean).join(": "),
      );
    case "pr_opened":
      return truncate(str(payload.url));
    case "repo_created":
      return truncate(str(payload.full_name));
    case "policy_limit_exceeded":
      return policyLimit(payload);
    default:
      return Object.keys(payload).length === 0 ? "" : truncate(JSON.stringify(payload));
  }
}
