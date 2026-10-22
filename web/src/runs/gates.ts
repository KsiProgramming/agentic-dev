import type { RunEvent } from "./types";

/** A gate the run is waiting at, from its `gate_waiting` event. */
export interface PendingGate {
  nodeId: string;
  title: string;
  prompt: string | null;
  /** The gate's input, shown to the approver: data, never instructions. */
  artifact: string;
}

/** The gate the run waits at: the last `gate_waiting` with no `gate_decided` after it. */
export function pendingGate(events: RunEvent[]): PendingGate | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (!event || event.node_id == null) continue;
    if (event.type === "gate_decided") return null;
    if (event.type === "gate_waiting") {
      const { title, prompt, artifact } = event.payload ?? {};
      return {
        nodeId: event.node_id,
        title: typeof title === "string" ? title : "Approve?",
        prompt: typeof prompt === "string" ? prompt : null,
        artifact: typeof artifact === "string" ? artifact : "",
      };
    }
  }
  return null;
}

/** The URL of the pull request the run opened, if it is a GitHub pull request URL. Payloads are
 * data, so anything else (e.g. a `javascript:` URL) is not offered as a link. */
export function pullRequestUrl(events: RunEvent[]): string | null {
  const opened = events.findLast((e) => e.type === "pr_opened");
  const url = opened?.payload?.url;
  if (typeof url !== "string") return null;
  return /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+$/.test(url) ? url : null;
}
