"use client";

import { IdChip, RelativeTime } from "@/components/display";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { repoLabel } from "@/runs/summaries";

import { actionInfo, describe, type AuditEvent } from "./actions";

/** Why a person's name is missing: there are no users yet. */
const NO_ACTOR = "Who acted is recorded once sign-in exists.";

function Time({ event, now }: { event: AuditEvent; now: number }) {
  return <RelativeTime iso={event.at} now={now} focusable={false} />;
}

function Action({ event }: { event: AuditEvent }) {
  const { label, icon: Icon } = actionInfo(event.action);
  return (
    <span className="inline-flex items-center gap-1.5 font-medium">
      {Icon ? <Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" /> : null}
      {label}
    </span>
  );
}

function Actor({ event }: { event: AuditEvent }) {
  if (event.actor.type === "system") return <span>System</span>;
  if (event.actor.id) return <span className="font-mono text-xs">{event.actor.id}</span>;
  return (
    <span title={NO_ACTOR} className="text-muted-foreground">
      —<span className="sr-only">{NO_ACTOR}</span>
    </span>
  );
}

/** The entry's run, linked to its console, with its template and repo; "—" for settings. */
function RunRef({ event }: { event: AuditEvent }) {
  if (!event.run_id) return <span className="text-muted-foreground">—</span>;
  const context = [event.run?.template_id, event.run?.repo_url && repoLabel(event.run.repo_url)]
    .filter(Boolean)
    .join(" · ");
  return (
    <span className="flex min-w-0 flex-col">
      <IdChip id={event.run_id} label="run" href={`/runs/${event.run_id}`} className="text-xs" />
      {context ? (
        <span className="truncate text-xs text-muted-foreground" title={context}>
          {context}
        </span>
      ) : null}
    </span>
  );
}

/** What the entry did, as text: `details` is data and is never rendered as HTML. */
function Details({ event }: { event: AuditEvent }) {
  const line = describe(event);
  return (
    <span className="line-clamp-2 break-words" title={line}>
      {line}
    </span>
  );
}

/** The audit log as a table, from `md` (768 px). */
export function AuditTable({ events, now }: { events: AuditEvent[]; now: number }) {
  return (
    <Table aria-label="Audit log" className="text-meta">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-28">Time</TableHead>
          <TableHead className="w-44">Action</TableHead>
          <TableHead className="w-20">Actor</TableHead>
          <TableHead className="w-44">Run</TableHead>
          <TableHead>Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map((event) => (
          <TableRow key={event.id} data-audit-id={event.id} data-action={event.action}>
            <TableCell>
              <Time event={event} now={now} />
            </TableCell>
            <TableCell>
              <Action event={event} />
            </TableCell>
            <TableCell>
              <Actor event={event} />
            </TableCell>
            <TableCell className="max-w-44">
              <RunRef event={event} />
            </TableCell>
            <TableCell className="max-w-0 whitespace-normal">
              <Details event={event} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** One entry as a card, below `md`. */
export function AuditCard({ event, now }: { event: AuditEvent; now: number }) {
  return (
    <Card size="sm" data-audit-id={event.id} data-action={event.action} className="gap-1.5 px-3">
      <div className="flex items-start justify-between gap-2">
        <Action event={event} />
        <span className="shrink-0 text-xs text-muted-foreground">
          <Time event={event} now={now} />
        </span>
      </div>
      <p className="text-sm">
        <Details event={event} />
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="sr-only">Actor </span>
          <Actor event={event} />
        </span>
        {event.run_id ? <RunRef event={event} /> : null}
      </div>
    </Card>
  );
}

/** The audit log as a table from `md` and as cards below. */
export function AuditList({ events, now }: { events: AuditEvent[]; now: number }) {
  return (
    <>
      <div className="hidden md:block">
        <AuditTable events={events} now={now} />
      </div>
      <ul aria-label="Audit log" className="flex flex-col gap-2 md:hidden">
        {events.map((event) => (
          <li key={event.id}>
            <AuditCard event={event} now={now} />
          </li>
        ))}
      </ul>
    </>
  );
}
