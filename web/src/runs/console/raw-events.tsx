"use client";

import { ChevronRightIcon } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { summarizePayload } from "../summarize";
import { foldDeltas, type RawRow } from "../timeline";
import type { ReceivedRunEvent } from "../types";

function rowType(row: RawRow<ReceivedRunEvent>): string {
  return row.kind === "text" ? "text_delta" : row.event.type;
}

function rowNode(row: RawRow<ReceivedRunEvent>): string | null {
  return row.kind === "text" ? row.nodeId : (row.event.node_id ?? null);
}

/** The text of a folded row, shortened like other payloads. */
function preview(text: string): string {
  return text.length > 400 ? `${text.slice(0, 399)}…` : text;
}

function FoldedRow({ row }: { row: Extract<RawRow<ReceivedRunEvent>, { kind: "text" }> }) {
  const [open, setOpen] = useState(false);
  const first = row.events[0];
  const last = row.events[row.events.length - 1] ?? first;
  const range = first.seq === last.seq ? `${first.seq}` : `${first.seq}–${last.seq}`;
  return (
    <>
      <TableRow
        data-testid="event-row"
        data-seq={first.seq}
        data-last-seq={last.seq}
        data-type="text_delta"
        data-chunks={row.events.length}
        data-created-at={first.created_at}
        data-received-at={first.receivedAt}
        className="align-top"
      >
        <TableCell className="text-muted-foreground tabular-nums">{range}</TableCell>
        <TableCell className="text-muted-foreground tabular-nums">
          {new Date(first.created_at).toLocaleTimeString()}
        </TableCell>
        <TableCell className="font-mono">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex items-center gap-1 rounded-sm text-left outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            <ChevronRightIcon
              aria-hidden="true"
              className={`size-3.5 shrink-0 motion-safe:transition-transform ${open ? "rotate-90" : ""}`}
            />
            text_delta × {row.events.length}
          </button>
        </TableCell>
        <TableCell className="font-mono text-muted-foreground">
          {row.nodeId ?? ""}
          {row.item !== null ? ` [${row.item}]` : ""}
        </TableCell>
        <TableCell className="min-w-64 break-words whitespace-pre-wrap">
          {preview(row.text)}
        </TableCell>
      </TableRow>
      {open
        ? row.events.map((event) => (
            <TableRow key={event.seq} data-testid="chunk-row" className="bg-muted/40 align-top">
              <TableCell className="pl-6 text-muted-foreground tabular-nums">{event.seq}</TableCell>
              <TableCell className="text-muted-foreground tabular-nums">
                {new Date(event.created_at).toLocaleTimeString()}
              </TableCell>
              <TableCell className="font-mono text-muted-foreground">chunk</TableCell>
              <TableCell />
              <TableCell className="font-mono break-all whitespace-pre-wrap">
                {JSON.stringify(event.payload?.text ?? "")}
              </TableCell>
            </TableRow>
          ))
        : null}
    </>
  );
}

/**
 * The run's event log as a table, for debugging and audit. Chunks of one streamed message are
 * folded into one row (expandable to the chunks). Payloads are rendered as text only.
 */
export function RawEvents({ events }: { events: ReceivedRunEvent[] }) {
  const typeId = useId();
  const nodeId = useId();
  const [type, setType] = useState("");
  const [node, setNode] = useState("");
  const rows = useMemo(() => foldDeltas(events), [events]);
  const types = useMemo(() => [...new Set(rows.map(rowType))].sort(), [rows]);
  const nodes = useMemo(
    () => [...new Set(rows.map(rowNode).filter((n): n is string => n !== null))].sort(),
    [rows],
  );
  const shown = rows.filter(
    (row) => (!type || rowType(row) === type) && (!node || rowNode(row) === node),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor={typeId} className="sr-only">
          Event type
        </Label>
        <NativeSelect id={typeId} size="sm" value={type} onChange={(e) => setType(e.target.value)}>
          <NativeSelectOption value="">All types</NativeSelectOption>
          {types.map((t) => (
            <NativeSelectOption key={t} value={t}>
              {t}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <Label htmlFor={nodeId} className="sr-only">
          Node
        </Label>
        <NativeSelect id={nodeId} size="sm" value={node} onChange={(e) => setNode(e.target.value)}>
          <NativeSelectOption value="">All nodes</NativeSelectOption>
          {nodes.map((n) => (
            <NativeSelectOption key={n} value={n}>
              {n}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <span className="text-xs text-muted-foreground tabular-nums">{events.length} events</span>
      </div>
      <Table className="text-[13px]" scrollLabel="Run events">
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Time</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Node</TableHead>
            <TableHead>Details</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((row) => {
            if (row.kind === "text") return <FoldedRow key={row.events[0].seq} row={row} />;
            const event = row.event;
            return (
              <TableRow
                key={event.seq}
                data-testid="event-row"
                data-seq={event.seq}
                data-last-seq={event.seq}
                data-type={event.type}
                data-created-at={event.created_at}
                data-received-at={event.receivedAt}
                className="align-top"
              >
                <TableCell className="text-muted-foreground tabular-nums">{event.seq}</TableCell>
                <TableCell className="text-muted-foreground tabular-nums">
                  {new Date(event.created_at).toLocaleTimeString()}
                </TableCell>
                <TableCell className="font-mono">{event.type}</TableCell>
                <TableCell className="font-mono text-muted-foreground">
                  {event.node_id ?? ""}
                </TableCell>
                <TableCell className="min-w-64 break-all whitespace-pre-wrap">
                  {summarizePayload(event)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
