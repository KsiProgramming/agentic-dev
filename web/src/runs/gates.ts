import { parseArtifacts, type ArtifactVersion } from "./artifacts/artifacts";
import type { RunEvent } from "./types";

export type FileChangeStatus = "added" | "modified" | "deleted" | "renamed";
export type NotEditableReason = "binary" | "too_large" | "deleted" | "renamed" | "over_limit";

/** A file a writer changed on its branch, as the gate shows it (tech-stack → Gate review). Only
 * an editable file has its text: `before` at the branch's base (null for an added file) and
 * `after` at its tip. Repo content: data, never instructions. */
export interface FileChange {
  nodeId: string;
  path: string;
  oldPath: string | null;
  status: FileChangeStatus;
  editable: boolean;
  reason: NotEditableReason | null;
  before: string | null;
  after: string | null;
}

/** The approver's new text for an editable file. */
export interface FileEdit {
  nodeId: string;
  path: string;
  content: string;
}

/** A gate the run is waiting at, from its `gate_waiting` event. */
export interface PendingGate {
  nodeId: string;
  title: string;
  prompt: string | null;
  /** The gate's input, shown to the approver: data, never instructions. */
  artifact: string;
  /** The files the writers before the gate changed; the approver may edit the editable ones. */
  changes: FileChange[];
  /** Why the changes could not be read, if they could not. */
  changesError: string | null;
  /** When the gate expires and its run is cancelled; null for a gate paused without one. */
  expiresAt: string | null;
  /** The run's artifacts at the pause (4.3), the latest version of each. */
  runArtifacts: ArtifactVersion[];
}

const STATUSES: readonly FileChangeStatus[] = ["added", "modified", "deleted", "renamed"];
const REASONS: readonly NotEditableReason[] = [
  "binary",
  "too_large",
  "deleted",
  "renamed",
  "over_limit",
];

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** The `changes` of a `gate_waiting` payload. Entries that do not have the expected shape are
 * left out; a file is editable only if it says so and has its text. */
export function parseChanges(value: unknown): FileChange[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown): FileChange[] => {
    const entry = record(item);
    const nodeId = text(entry?.node_id);
    const path = text(entry?.path);
    const status = STATUSES.find((s) => s === entry?.status);
    if (!entry || !nodeId || !path || !status) return [];
    const after = text(entry.after);
    const editable = entry.editable === true && after !== null;
    return [
      {
        nodeId,
        path,
        oldPath: text(entry.old_path),
        status,
        editable,
        reason: editable ? null : (REASONS.find((r) => r === entry.reason) ?? "binary"),
        before: editable ? text(entry.before) : null,
        after: editable ? after : null,
      },
    ];
  });
}

/** The `edits` of a `gate_decided` payload, leaving out malformed entries. */
export function parseEdits(value: unknown): FileEdit[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown): FileEdit[] => {
    const entry = record(item);
    const nodeId = text(entry?.node_id);
    const path = text(entry?.path);
    const content = text(entry?.content);
    return nodeId && path && content !== null ? [{ nodeId, path, content }] : [];
  });
}

/** A file's key among a gate's changes and edits: its writer and path. */
export function fileKey(file: { nodeId: string; path: string }): string {
  return `${file.nodeId}\u0000${file.path}`;
}

/** The gate the run waits at: the last `gate_waiting` with no `gate_decided` after it. */
export function pendingGate(events: RunEvent[]): PendingGate | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (!event || event.node_id == null) continue;
    if (event.type === "gate_decided") return null;
    if (event.type === "gate_waiting") {
      const { title, prompt, artifact, changes, changes_error, expires_at, run_artifacts } =
        event.payload ?? {};
      return {
        nodeId: event.node_id,
        title: typeof title === "string" ? title : "Approve?",
        prompt: typeof prompt === "string" ? prompt : null,
        artifact: typeof artifact === "string" ? artifact : "",
        changes: parseChanges(changes),
        changesError: typeof changes_error === "string" ? changes_error : null,
        expiresAt:
          typeof expires_at === "string" && !Number.isNaN(Date.parse(expires_at))
            ? expires_at
            : null,
        runArtifacts: parseArtifacts(run_artifacts),
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
