import { summarizePayload } from "../summarize";
import type { RawRow } from "../timeline";
import type { RunEvent } from "../types";

/** A row's type: a folded run of chunks is `text_delta`. */
export function rowType<E extends RunEvent>(row: RawRow<E>): string {
  return row.kind === "text" ? "text_delta" : row.event.type;
}

/** The node a row belongs to, if any. */
export function rowNode<E extends RunEvent>(row: RawRow<E>): string | null {
  return row.kind === "text" ? row.nodeId : (row.event.node_id ?? null);
}

export function rowEvents<E extends RunEvent>(row: RawRow<E>): E[] {
  return row.kind === "text" ? row.events : [row.event];
}

/** How long after `startIso` (the first event) the row's first event was written. */
export function rowOffsetMs<E extends RunEvent>(row: RawRow<E>, startIso: string): number {
  const first = rowEvents(row)[0]!;
  return Math.max(0, Date.parse(first.created_at) - Date.parse(startIso));
}

function oneLine(text: string, max = 160): string {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

/** One line on what the row holds: its payload summed up, a folded message's text. Never JSON
 * shown as a table's content: the payload opens in the event drawer. */
export function rowSummary<E extends RunEvent>(row: RawRow<E>): string {
  return oneLine(row.kind === "text" ? row.text : summarizePayload(row.event));
}
