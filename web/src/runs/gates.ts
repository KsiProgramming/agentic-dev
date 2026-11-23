import { parseArtifacts, type ArtifactVersion } from "./artifacts/artifacts";
import { parseBreaker, type BreakerTrip } from "./breaker";
import { parseEvidence, type Evidence } from "./evidence";
import { parsePlans, type WritePlan } from "./plans";
import { parseReview, type Review } from "./review";
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
  /** Why the file is protected (13.5), when it is: by the platform, by the workflow, or because
   * an earlier writer's approved work holds it. */
  protected: ProtectedRule | null;
}

/** Where a protection comes from (13.5). */
export type ProtectedRule = "default" | "workflow" | "frozen";

/** What each protection says it is, for people. */
export const PROTECTED_RULE_LABEL: Record<ProtectedRule, string> = {
  default: "Platform: CI and analyzer config",
  workflow: "This workflow",
  frozen: "Approved tests",
};

/** A writer's refused tries to change one protected path (13.5), counted. The path is a name,
 * never content. */
export interface ProtectedAttempt {
  nodeId: string;
  path: string;
  rule: ProtectedRule;
  count: number;
}

const RULES: readonly ProtectedRule[] = ["default", "workflow", "frozen"];

/** The `protected_attempts` of `GET /runs/{id}/gate`; malformed entries are left out. */
export function parseProtectedAttempts(value: unknown): ProtectedAttempt[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown): ProtectedAttempt[] => {
    const entry = record(item);
    const nodeId = text(entry?.node_id);
    const path = text(entry?.path);
    const rule = RULES.find((r) => r === entry?.rule);
    const count = typeof entry?.count === "number" ? entry.count : 0;
    return nodeId && path && rule && count > 0 ? [{ nodeId, path, rule, count }] : [];
  });
}

/** The attempts of a run's `protected_path_refused` events, grouped by writer, path and rule,
 * the most tried first (the order `GET /runs/{id}/gate` answers in). */
export function attemptsFromEvents(events: RunEvent[]): ProtectedAttempt[] {
  const found = new Map<string, ProtectedAttempt>();
  for (const event of events) {
    if (event.type !== "protected_path_refused" || event.node_id == null) continue;
    const path = text(event.payload?.path);
    const rule = text(record(event.payload?.rule)?.kind);
    const kind = RULES.find((r) => r === rule);
    if (!path || !kind) continue;
    const key = `${event.node_id}\u0000${path}\u0000${kind}`;
    const seen = found.get(key);
    if (seen) seen.count += 1;
    else found.set(key, { nodeId: event.node_id, path, rule: kind, count: 1 });
  }
  return [...found.values()].sort((a, b) => b.count - a.count || a.path.localeCompare(b.path));
}

/** The approver's new text for an editable file. */
export interface FileEdit {
  nodeId: string;
  path: string;
  content: string;
}

/** What a selection gate shows (6.7): the items of a JSON run artifact (its `items` array, read
 * from that version of `artifact`), the keys that can be chosen in item order, those checked when
 * it opened, and the fewest an approval chooses. */
export interface GateSelection {
  artifact: string;
  version: number;
  items: string;
  key: string;
  count: number;
  keys: string[];
  preselected: string[];
  min: number;
}

/** The `select` of a `gate_waiting` payload or of `GET /runs/{id}/gate`; null when the gate does
 * not select, or the value does not have the expected shape. */
export function parseSelection(value: unknown): GateSelection | null {
  const entry = record(value);
  if (!entry) return null;
  const strings = (v: unknown) =>
    Array.isArray(v) && v.every((k) => typeof k === "string") ? (v as string[]) : null;
  const keys = strings(entry.keys);
  const preselected = strings(entry.preselected);
  const { artifact, version, items, key, count, min } = entry;
  if (
    typeof artifact !== "string" ||
    typeof version !== "number" ||
    typeof items !== "string" ||
    typeof key !== "string" ||
    typeof count !== "number" ||
    typeof min !== "number" ||
    !keys ||
    !preselected
  ) {
    return null;
  }
  return { artifact, version, items, key, count, keys, preselected, min };
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
  /** A selection gate's items (6.7); null for a gate that does not select. */
  select: GateSelection | null;
  /** What rejecting does: cancel the run, or end it here as completed (6.7). */
  onReject: "cancel" | "end";
  /** How many more times the approver may send the work back with comments (7.8); 0 offers
   * Approve and Reject only. */
  changesLeft: number;
  /** Which pass of the gate this is: a gate in a loop pauses once per pass (7.8). */
  iteration: number;
  /** Set when the run waits for an answer on a Jira issue (7.9), not for a decision: nobody
   * approves it; the platform goes on when the answer is found. */
  waitFor: WaitFor | null;
  /** What the platform's checks found about the writer's work before this gate (13.3); null
   * for a gate that does not check. */
  evidence: Evidence | null;
  /** What the independent review found (13.6): the comments to dismiss or keep, and the lenses
   * that could not run; null for a gate with no review. */
  review: Review | null;
  /** The run's refused tries to change a protected path so far (13.5), most tried first. */
  protectedAttempts: ProtectedAttempt[];
  /** Set when a circuit breaker paused the run (13.7), not a gate: what it saw. The decision is
   * Resume or Cancel run, and nothing else. */
  breaker: BreakerTrip | null;
  /** What approving does (13.8): the plan of each outward write the gate guards, in run order. */
  plans: WritePlan[];
}

/** The title of a pause a circuit breaker caused. */
export function pausedTitle(trip: BreakerTrip): string {
  return `Paused: ${trip.reason}`;
}

/** What a `wait_for` waits for: a comment on the issue after the one the platform posted. */
export interface WaitFor {
  issueKey: string;
  /** The issue's address, only when it is an https URL: it is data, never trusted as a link. */
  issueUrl: string | null;
}

/** The `wait_for` of a `gate_waiting` payload; null for a gate or a value of another shape. */
export function parseWaitFor(value: unknown): WaitFor | null {
  const issue = record(record(value)?.issue);
  const key = text(issue?.key);
  if (!key) return null;
  const url = text(issue?.url);
  return { issueKey: key, issueUrl: url && /^https:\/\//.test(url) ? url : null };
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
        protected:
          entry.protected === true ? (RULES.find((r) => r === entry.rule) ?? "default") : null,
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
      const {
        title,
        prompt,
        artifact,
        changes,
        changes_error,
        expires_at,
        run_artifacts,
        select,
        on_reject,
        on_changes,
        wait_for,
        evidence,
        review,
        plans,
      } = event.payload ?? {};
      const trip =
        typeof event.payload?.breaker === "string"
          ? parseBreaker(
              events
                .slice(0, i)
                .findLast((e) => e.type === "breaker_tripped" && e.node_id === event.node_id)
                ?.payload,
            )
          : null;
      const iteration = events
        .slice(0, i + 1)
        .filter((e) => e.type === "gate_waiting" && e.node_id === event.node_id).length;
      return {
        nodeId: event.node_id,
        title: trip ? pausedTitle(trip) : typeof title === "string" ? title : "Approve?",
        prompt: typeof prompt === "string" ? prompt : null,
        artifact: typeof artifact === "string" ? artifact : "",
        changes: parseChanges(changes),
        changesError: typeof changes_error === "string" ? changes_error : null,
        expiresAt:
          typeof expires_at === "string" && !Number.isNaN(Date.parse(expires_at))
            ? expires_at
            : null,
        runArtifacts: parseArtifacts(run_artifacts),
        select: parseSelection(select),
        onReject: on_reject === "end" ? "end" : "cancel",
        changesLeft: typeof on_changes === "number" ? Math.max(on_changes - iteration + 1, 0) : 0,
        iteration,
        waitFor: parseWaitFor(wait_for),
        evidence: parseEvidence(evidence),
        review: parseReview(review),
        protectedAttempts: attemptsFromEvents(events.slice(0, i)),
        breaker: trip,
        plans: parsePlans(plans),
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
