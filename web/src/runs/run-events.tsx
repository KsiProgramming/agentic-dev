"use client";

import { ExternalLinkIcon, RadioIcon } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorState } from "@/components/states";
import { StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { GatePanel } from "./gate-panel";
import { pendingGate, pullRequestUrl } from "./gates";
import { displayStatus } from "./status";
import { summarizePayload } from "./summarize";
import { useRunEvents } from "./use-run-events";

/** The live event list of one run. Retry reconnects by mounting a fresh stream. */
export function RunEvents({ runId, baseUrl }: { runId: string; baseUrl?: string }) {
  const [attempt, setAttempt] = useState(0);
  return (
    <RunEventStream
      key={attempt}
      runId={runId}
      baseUrl={baseUrl}
      onRetry={() => setAttempt((n) => n + 1)}
    />
  );
}

/** Payloads are rendered as text only: they are data. */
function RunEventStream({
  runId,
  baseUrl,
  onRetry,
}: {
  runId: string;
  baseUrl?: string;
  onRetry: () => void;
}) {
  const { events, status } = useRunEvents(runId, baseUrl);
  const gate = status === "live" ? pendingGate(events) : null;
  const pullRequest = pullRequestUrl(events);
  const shown = displayStatus(status, gate !== null);

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold tracking-tight">
          Run <code className="font-mono text-base font-normal break-all">{runId}</code>
        </h1>
        <span aria-live="polite">
          <StatusBadge data-testid="run-status" status={shown.status} label={shown.label} />
        </span>
      </header>

      {status === "not_found" ? <ErrorState message="Run not found." /> : null}
      {status === "error" ? (
        <ErrorState message="Lost the connection to the event stream." onRetry={onRetry} />
      ) : null}

      {gate ? <GatePanel key={gate.nodeId} runId={runId} gate={gate} baseUrl={baseUrl} /> : null}

      {pullRequest ? (
        <p data-testid="pull-request" className="flex flex-wrap items-center gap-1.5">
          <span className="text-muted-foreground">Pull request opened:</span>
          <a
            href={pullRequest}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-mono break-all text-primary underline-offset-4 hover:underline"
          >
            {pullRequest}
            <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
          </a>
        </p>
      ) : null}

      {events.length === 0 && (status === "connecting" || status === "live") ? (
        <EmptyState icon={RadioIcon} message="Waiting for events…" />
      ) : null}

      {events.length > 0 ? (
        <Table className="text-[13px]">
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
            {events.map((event) => (
              <TableRow
                key={event.seq}
                data-testid="event-row"
                data-seq={event.seq}
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
            ))}
          </TableBody>
        </Table>
      ) : null}
    </section>
  );
}
