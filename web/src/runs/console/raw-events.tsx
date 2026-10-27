"use client";

import { useId, useMemo, useState } from "react";

import { Duration, RelativeTime } from "@/components/display";
import { JsonView, TextView } from "@/components/json-view";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";

import { foldDeltas, type RawRow } from "../timeline";
import type { ReceivedRunEvent } from "../types";
import { rowEvents, rowNode, rowOffsetMs, rowSummary, rowType } from "./event-rows";

type Row = RawRow<ReceivedRunEvent>;

function rowSeq(row: Row): string {
  const events = rowEvents(row);
  const first = events[0]!.seq;
  const last = events.at(-1)!.seq;
  return first === last ? `${first}` : `${first}–${last}`;
}

/** One event's payload, or a folded message's text and chunks, in a side drawer. JSON is shown
 * here, never in the table. */
function EventDrawer({ row, onClose }: { row: Row | null; onClose: () => void }) {
  const wide = useMediaQuery(MD_UP);
  return (
    <Sheet open={row !== null} onOpenChange={(open) => (open ? null : onClose())}>
      {row ? (
        <SheetContent
          side={wide ? "right" : "bottom"}
          data-testid="event-drawer"
          className="data-[side=bottom]:max-h-[85svh] data-[side=right]:w-full! data-[side=right]:sm:max-w-[560px]!"
        >
          <SheetHeader className="border-b pr-12">
            <SheetTitle className="font-mono break-all">
              {rowType(row)}
              {row.kind === "text" ? ` × ${row.events.length}` : ""}
            </SheetTitle>
            <SheetDescription className="flex flex-wrap items-center gap-x-2">
              <span>Event {rowSeq(row)}</span>
              {rowNode(row) ? (
                <>
                  <span aria-hidden="true">·</span>
                  <span className="font-mono">{rowNode(row)}</span>
                </>
              ) : null}
              <span aria-hidden="true">·</span>
              <RelativeTime iso={rowEvents(row)[0]!.created_at} clock />
            </SheetDescription>
          </SheetHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 pb-4">
            {row.kind === "text" ? (
              <>
                <TextView text={row.text} label="Message text" />
                <ol aria-label="Chunks" className="flex flex-col gap-1">
                  {row.events.map((event) => (
                    <li
                      key={event.seq}
                      data-testid="chunk-row"
                      className="flex min-w-0 gap-3 font-mono text-xs"
                    >
                      <span className="shrink-0 text-muted-foreground tabular-nums">
                        {event.seq}
                      </span>
                      <span className="min-w-0 break-all whitespace-pre-wrap">
                        {String(event.payload?.text ?? "")}
                      </span>
                    </li>
                  ))}
                </ol>
              </>
            ) : (
              <JsonView
                value={row.event.payload ?? {}}
                label={`Payload of event ${row.event.seq}`}
              />
            )}
          </div>
        </SheetContent>
      ) : null}
    </Sheet>
  );
}

/**
 * The run's event log, for debugging and audit: one 32 px row per event (chunks of one streamed
 * message folded into one), each opening its payload in a drawer. Filtered by type and step,
 * starting on `node` (the selected step's). Payloads are rendered as text only.
 */
export function RawEvents({
  events,
  node: initialNode = "",
}: {
  events: ReceivedRunEvent[];
  /** The step to show the events of first; "" for every step. */
  node?: string;
}) {
  const typeId = useId();
  const nodeId = useId();
  const [type, setType] = useState("");
  const [node, setNode] = useState(initialNode);
  const [open, setOpen] = useState<Row | null>(null);
  const rows = useMemo(() => foldDeltas(events), [events]);
  const types = useMemo(() => [...new Set(rows.map(rowType))].sort(), [rows]);
  const nodes = useMemo(
    () => [...new Set(rows.map(rowNode).filter((n): n is string => n !== null))].sort(),
    [rows],
  );
  const shown = rows.filter(
    (row) => (!type || rowType(row) === type) && (!node || rowNode(row) === node),
  );
  const start = events[0]?.created_at ?? null;

  return (
    <div className="flex min-w-0 flex-col gap-3">
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
          Step
        </Label>
        <NativeSelect id={nodeId} size="sm" value={node} onChange={(e) => setNode(e.target.value)}>
          <NativeSelectOption value="">All steps</NativeSelectOption>
          {/* The selected step stays listed even before it has events. */}
          {(node && !nodes.includes(node) ? [node, ...nodes] : nodes).map((n) => (
            <NativeSelectOption key={n} value={n}>
              {n}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <span className="text-xs text-muted-foreground tabular-nums">
          {shown.length} of {rows.length} rows · {events.length} events
        </span>
      </div>
      <Table className="text-meta" scrollLabel="Run events">
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Time</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Step</TableHead>
            <TableHead>Summary</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((row) => {
            const all = rowEvents(row);
            const first = all[0]!;
            return (
              <TableRow
                key={first.seq}
                data-testid="event-row"
                data-seq={first.seq}
                data-last-seq={all.at(-1)!.seq}
                data-type={rowType(row)}
                data-chunks={row.kind === "text" ? all.length : undefined}
                data-created-at={first.created_at}
                data-received-at={first.receivedAt}
                className="relative h-8"
              >
                <TableCell className="py-1 text-muted-foreground tabular-nums">
                  {rowSeq(row)}
                </TableCell>
                <TableCell className="py-1 text-muted-foreground">
                  {start ? (
                    <>
                      +<Duration ms={rowOffsetMs(row, start)} />
                    </>
                  ) : null}
                </TableCell>
                <TableCell className="py-1 font-mono">
                  {/* The row's one tab stop; it stretches over the whole row for the pointer. */}
                  <button
                    type="button"
                    onClick={() => setOpen(row)}
                    className="rounded-sm text-left outline-none after:absolute after:inset-0 hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                  >
                    {rowType(row)}
                    {row.kind === "text" ? ` × ${all.length}` : ""}
                    <span className="sr-only">, event {rowSeq(row)}: open the payload</span>
                  </button>
                </TableCell>
                <TableCell className="py-1 font-mono text-muted-foreground">
                  {rowNode(row) ?? ""}
                  {row.kind === "text" && row.item !== null ? ` [${row.item}]` : ""}
                </TableCell>
                <TableCell className="max-w-md truncate py-1">{rowSummary(row)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <EventDrawer row={open} onClose={() => setOpen(null)} />
    </div>
  );
}
