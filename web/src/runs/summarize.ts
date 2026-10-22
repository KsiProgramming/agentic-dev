import type { RunEvent } from "./types";

const MAX_LENGTH = 200;

function truncate(text: string): string {
  return text.length > MAX_LENGTH ? `${text.slice(0, MAX_LENGTH - 1)}…` : text;
}

function str(value: unknown): string {
  if (value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
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
    default:
      return Object.keys(payload).length === 0 ? "" : truncate(JSON.stringify(payload));
  }
}
