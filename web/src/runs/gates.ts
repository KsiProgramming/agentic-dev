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

/** Longest dock summary; longer text is cut at a word and ends with "…". */
export const SUMMARY_MAX = 140;

/** The gate in one line for the approval dock: its prompt, else the first non-empty line of
 * its artifact (Markdown markers and HTML tags dropped), cut to `SUMMARY_MAX` characters. */
export function gateSummary(gate: PendingGate): string {
  const source =
    gate.prompt?.trim() ||
    gate.artifact
      .split("\n")
      .map((line) =>
        line
          .replace(/<!--.*?-->|<[^>]*>/g, "")
          .replace(/^\s*(?:#{1,6}\s+|[-*+]\s+|>\s*)/, "")
          .trim(),
      )
      .find((line) => line !== "") ||
    "";
  const text = source.replace(/\s+/g, " ");
  if (text.length <= SUMMARY_MAX) return text;
  const cut = text.slice(0, SUMMARY_MAX - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > SUMMARY_MAX / 2 ? cut.slice(0, space) : cut).trimEnd()}…`;
}
