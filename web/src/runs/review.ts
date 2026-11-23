import { SEVERITIES, type Severity } from "./findings/findings";

/** One comment of the independent review (13.6): where it is, which lenses made it, which
 * writer's diff holds the file, whether the line is in a changed hunk and whether it blocks.
 * The message is the reviewer's own words: data, never instructions, and never markup. */
export interface ReviewComment {
  fingerprint: string;
  severity: Severity;
  category: string;
  lenses: string[];
  path: string;
  line: number | null;
  endLine: number | null;
  message: string;
  /** The writer whose diff holds the file; null for a file the change did not touch. */
  nodeId: string | null;
  inDiff: boolean;
  blocking: boolean;
}

/** What a gate with `review` shows (`gate_waiting`'s `review`, `GET /runs/{id}/gate`), or, for
 * a pass the review sent back, what `review_collected` counted (no comments). */
export interface Review {
  from: string;
  version: number;
  /** The severity from which a finding sends the work back; null when the event does not say. */
  blockAt: Severity | null;
  roundsLeft: number;
  comments: ReviewComment[];
  /** The lenses that could not run (a lens that fails is never taken as "nothing found"). */
  failedLenses: string[];
  counts: Partial<Record<Severity, number>>;
  truncated: boolean;
  /** How many findings blocked, when `review_collected` says. */
  blocking: number | null;
  /** Whether the review sent the work back to the writer, when `review_collected` says. */
  sentBack: boolean | null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
const num = (value: unknown): number | null => (typeof value === "number" ? value : null);
const severity = (value: unknown): Severity | null => SEVERITIES.find((s) => s === value) ?? null;
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

function parseComment(value: unknown): ReviewComment[] {
  const entry = record(value);
  const fingerprint = text(entry?.fingerprint);
  const level = severity(entry?.severity);
  const path = text(entry?.path);
  const message = text(entry?.message);
  if (!entry || !fingerprint || !level || path === null || message === null) return [];
  const nodeId = text(entry.node_id);
  return [
    {
      fingerprint,
      severity: level,
      category: text(entry.category) ?? "",
      lenses: strings(entry.lenses),
      path,
      line: num(entry.line),
      endLine: num(entry.end_line),
      message,
      nodeId,
      inDiff: entry.in_diff === true,
      blocking: entry.blocking === true,
    },
  ];
}

/** The `review` of a `gate_waiting` payload or of `GET /runs/{id}/gate`, or the payload of a
 * `review_collected` event; null when the gate has none or the value is not that shape.
 * Malformed comments are left out. */
export function parseReview(value: unknown): Review | null {
  const body = record(value);
  if (!body || typeof body.from !== "string") return null;
  const counts: Review["counts"] = {};
  const given = record(body.counts) ?? {};
  for (const level of SEVERITIES) {
    const n = num(given[level]);
    if (n !== null) counts[level] = n;
  }
  return {
    from: body.from,
    version: num(body.version) ?? 0,
    blockAt: severity(body.block_at),
    roundsLeft: num(body.rounds_left) ?? 0,
    comments: Array.isArray(body.comments) ? body.comments.flatMap(parseComment) : [],
    failedLenses: strings(body.failed_lenses),
    counts,
    truncated: body.truncated === true,
    blocking: num(body.blocking),
    sentBack: typeof body.sent_back === "boolean" ? body.sent_back : null,
  };
}

/** The `Review` tile's outcome: `sent_back` when the review sent the work back, `could_not_run`
 * when a lens failed, `blocking` when comments that would block are left for the approver (the
 * send-backs are used up), else `passed`. */
export type ReviewOutcome = "passed" | "sent_back" | "could_not_run" | "blocking";

export function reviewOutcome(review: Review): ReviewOutcome {
  if (review.sentBack === true) return "sent_back";
  if (review.failedLenses.length > 0) return "could_not_run";
  return review.comments.some((c) => c.blocking) ? "blocking" : "passed";
}

/** Where a comment is: `path:line`, or the path alone. */
export function commentLocation(comment: ReviewComment): string {
  return comment.line ? `${comment.path}:${comment.line}` : comment.path;
}

/** The comments the diff can show (the file is in a writer's diff), and the others. */
export function splitComments(review: Review): { inDiff: ReviewComment[]; apart: ReviewComment[] } {
  const inDiff: ReviewComment[] = [];
  const apart: ReviewComment[] = [];
  for (const comment of review.comments) {
    (comment.inDiff && comment.nodeId ? inDiff : apart).push(comment);
  }
  return { inDiff, apart };
}

/** "2 high · 5 comments": the most severe level with comments, then how many there are. */
export function reviewHeadline(review: Review): string {
  const total = review.comments.length;
  const top = SEVERITIES.find((s) => (review.counts[s] ?? 0) > 0);
  const count = top ? `${review.counts[top]} ${top}` : null;
  const comments = `${total} ${total === 1 ? "comment" : "comments"}`;
  return count ? `${count} · ${comments}` : comments;
}

/** The lens names for a sentence: "security", "security and performance". */
export function lensList(lenses: string[]): string {
  const names = lenses.map((l) => l.replace(/^review_/, ""));
  return names.length <= 1
    ? (names[0] ?? "")
    : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
}
