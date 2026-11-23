import { SEVERITY_DISPLAY } from "../findings/findings";
import { lensList, type ReviewComment } from "../review";

/** A comment as the diff's view zone needs it: the line it sits under and what it says. */
export type ZoneComment = Pick<
  ReviewComment,
  "fingerprint" | "severity" | "lenses" | "message" | "blocking"
> & { line: number };

/** The comments of one file of one writer's diff that can sit under a line of its changed side. */
export function zoneComments(
  comments: ReviewComment[],
  file: { nodeId: string; path: string },
): ZoneComment[] {
  return comments.flatMap((c) =>
    c.nodeId === file.nodeId && c.path === file.path && c.inDiff && c.line && c.line > 0
      ? [{ ...c, line: c.line }]
      : [],
  );
}

/** Each severity's own hue, written out in full so Tailwind sees the classes (design-language.md
 * → Comments in a diff). */
const ZONE_TONE: Record<ZoneComment["severity"], string> = {
  critical: "border-severity-critical text-severity-critical",
  high: "border-severity-high text-severity-high",
  medium: "border-severity-medium text-severity-medium",
  low: "border-severity-low text-severity-low",
  info: "border-severity-info text-severity-info",
};

/** Characters that fit a line of a zone, to size it before Monaco lays it out. */
const CHARS_PER_LINE = 90;
const LINE_PX = 18;

/** The zone's height: a header line, the message's lines and the padding. */
export function zoneHeight(comment: ZoneComment): number {
  const lines = comment.message
    .split("\n")
    .reduce((n, line) => n + Math.max(1, Math.ceil(line.length / CHARS_PER_LINE)), 0);
  return LINE_PX * (lines + 1) + 12;
}

/**
 * The DOM of one comment under its line: the severity word, the lenses and the message. It is
 * built from text nodes (`textContent`), never from markup, because the message is a
 * reviewer's words. Colours are the theme's tokens, so it follows light and dark.
 */
export function zoneElement(comment: ZoneComment, doc: Document = document): HTMLElement {
  const root = doc.createElement("div");
  root.setAttribute("data-review-zone", comment.fingerprint);
  root.setAttribute("role", "note");
  root.className = `m-1 box-border overflow-auto rounded-sm border-l-4 bg-surface-subtle px-3 py-1.5 font-sans text-meta ${ZONE_TONE[comment.severity]}`;

  const head = doc.createElement("div");
  head.className = "flex flex-wrap items-center gap-x-2 font-medium";
  const severity = doc.createElement("span");
  severity.textContent = SEVERITY_DISPLAY[comment.severity].label;
  head.append(severity);
  if (comment.blocking) {
    const blocking = doc.createElement("span");
    blocking.textContent = "Blocking";
    head.append(blocking);
  }
  if (comment.lenses.length > 0) {
    const lenses = doc.createElement("span");
    lenses.className = "font-mono text-caption text-foreground-secondary";
    lenses.textContent = lensList(comment.lenses);
    head.append(lenses);
  }

  const message = doc.createElement("div");
  message.className = "break-words whitespace-pre-wrap text-foreground";
  message.textContent = comment.message;
  root.append(head, message);
  return root;
}
