"use client";

import {
  ArrowRightIcon,
  CircleSlashIcon,
  ExternalLinkIcon,
  FileSearchIcon,
  GitBranchIcon,
} from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import { ApiError } from "@/api/errors";
import { Duration, ExpiresIn, IdChip, Money, StatTile, WaitingTime } from "@/components/display";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { usageOfRun } from "@/runs/cost";
import {
  ApproveButton,
  GateArtifact,
  GateDecisionDialogs,
  plural,
  RejectButton,
} from "@/runs/console/decision-controls";
import { StatusLabel } from "@/runs/console/gate-files";
import { useGateDecision, type Decision } from "@/runs/console/use-gate-decision";
import { fileKey } from "@/runs/gates";
import { repoLabel, runTimes, type RunSummary } from "@/runs/summaries";

import { useRunGate, type InboxGate } from "./use-run-gate";

/** Changed files listed in the review before "and N more". */
const FILES_SHOWN = 6;

/**
 * The review of the gate a run waits at, beside the Inbox's list (tech-stack → Inbox): what
 * approving does, the run's active time and cost so far, the summary or the changed files (the
 * review sheet's diff view, editable), then Approve, Reject and Open run. `A` / `R` work as in
 * the approval dock while `shortcuts` is on; the decision is the dock's (`useGateDecision`).
 */
export function InboxReview({
  run,
  now,
  baseUrl,
  shortcuts,
  onDecided,
}: {
  run: RunSummary;
  now: number;
  baseUrl: string;
  shortcuts: boolean;
  onDecided: (decision: Decision) => void;
}) {
  const gate = useRunGate(run.id, run.waiting_gate?.node_id, { baseUrl });
  if (gate.isPending) return <LoadingState rows={6} label="Loading the gate…" />;
  if (!gate.data) {
    if (gate.error instanceof ApiError && gate.error.status === 409) {
      return <NoLongerWaiting runId={run.id} />;
    }
    return (
      <ErrorState
        message={gate.error?.message ?? "Could not load the gate."}
        onRetry={() => void gate.refetch()}
      />
    );
  }
  return (
    <GateReview
      key={`${run.id}:${gate.data.nodeId}`}
      run={run}
      gate={gate.data}
      now={now}
      baseUrl={baseUrl}
      shortcuts={shortcuts}
      onDecided={onDecided}
    />
  );
}

/** A selected run whose gate was decided or expired, or that is not in the Inbox. */
export function NoLongerWaiting({ runId }: { runId: string }) {
  return (
    <EmptyState
      icon={CircleSlashIcon}
      message="This run no longer waits for a decision."
      action={
        <Button asChild variant="outline">
          <Link href={`/runs/${runId}`}>Open run</Link>
        </Button>
      }
    />
  );
}

function GateReview({
  run,
  gate,
  now,
  baseUrl,
  shortcuts,
  onDecided,
}: {
  run: RunSummary;
  gate: InboxGate;
  now: number;
  baseUrl: string;
  shortcuts: boolean;
  onDecided: (decision: Decision) => void;
}) {
  const headingId = useId();
  const decision = useGateDecision({ runId: run.id, gate, baseUrl, shortcuts, onDecided });
  const times = runTimes(run, now);

  return (
    <section
      aria-labelledby={headingId}
      data-testid="inbox-review"
      className="flex min-w-0 flex-col gap-4 rounded-lg border bg-card p-4"
    >
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <h2 id={headingId} className="text-section font-semibold">
            {gate.title}
          </h2>
          {gate.expiresAt ? (
            <ExpiresIn iso={gate.expiresAt} className="text-meta text-muted-foreground" />
          ) : null}
        </div>
        <p className="flex flex-wrap items-center gap-x-2 text-meta text-muted-foreground">
          <span>{run.workflow.name}</span>
          <IdChip id={run.id} label="run id" />
        </p>
        {gate.prompt ? <p className="text-muted-foreground">{gate.prompt}</p> : null}
      </header>

      <ApprovingDoes gate={gate} />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <StatTile
          label="Active time"
          value={<Duration ms={times.activeMs} />}
          secondary={<WaitingTime ms={times.waitingMs} live />}
        />
        <StatTile
          label="Cost so far"
          value={<Money usage={usageOfRun(run.usage)} budget={run.usage.budget_usd ?? null} />}
        />
      </div>

      {gate.changes.length > 0 ? (
        <ChangedFiles gate={gate} onReview={() => decision.setDetails(true)} />
      ) : (
        <div className="max-h-96 overflow-y-auto rounded-md border p-3">
          <GateArtifact gate={gate} />
        </div>
      )}

      {decision.error && !decision.rejecting ? (
        <Alert variant="destructive">
          <AlertDescription>{decision.error}</AlertDescription>
        </Alert>
      ) : null}

      {decision.sent ? (
        <p role="status" className="font-medium">
          {decision.sent === "approve" ? "Approved" : "Rejected"}. The run carries on shortly.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap sm:items-center">
          <ApproveButton decision={decision} shortcut={shortcuts} />
          <RejectButton decision={decision} shortcut={shortcuts} />
          <Button asChild variant="ghost" className="sm:ml-auto">
            <Link href={`/runs/${run.id}`}>
              <ExternalLinkIcon aria-hidden="true" data-icon="inline-start" />
              Open run
            </Link>
          </Button>
        </div>
      )}
      <GateDecisionDialogs decision={decision} />
    </section>
  );
}

/** What approving lets happen: the writers' branches go on towards their base, in the repo. */
function ApprovingDoes({ gate }: { gate: InboxGate }) {
  const base = gate.base ?? "default branch";
  return (
    <section aria-label="What approving does" className="flex flex-col gap-1 text-meta">
      <h3 className="text-caption text-muted-foreground">Approving lets the run go on</h3>
      {gate.repoUrl ? (
        <p>
          In <span className="font-mono">{repoLabel(gate.repoUrl)}</span>
        </p>
      ) : null}
      {gate.branches.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {gate.branches.map((b) => (
            <li key={b.nodeId} className="flex min-w-0 flex-wrap items-center gap-1.5">
              <GitBranchIcon aria-hidden="true" className="size-4 text-muted-foreground" />
              <span className="font-mono break-all">{b.branch}</span>
              <ArrowRightIcon aria-hidden="true" className="size-4 text-muted-foreground" />
              <span className="sr-only">into</span>
              <span className={gate.base ? "font-mono" : "text-muted-foreground"}>{base}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground">No files changed before this gate.</p>
      )}
    </section>
  );
}

/** The gate's changed files in short, and the button that opens them in the review sheet. */
function ChangedFiles({ gate, onReview }: { gate: InboxGate; onReview: () => void }) {
  const shown = gate.changes.slice(0, FILES_SHOWN);
  const more = gate.changes.length - shown.length;
  return (
    <section aria-label="Changed files" className="flex flex-col gap-2">
      <ul className="flex flex-col divide-y rounded-md border">
        {shown.map((change) => (
          <li
            key={fileKey(change)}
            className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-0.5 px-3 py-2"
          >
            <span className="min-w-0 font-mono text-meta break-all">{change.path}</span>
            <StatusLabel status={change.status} />
          </li>
        ))}
      </ul>
      {more > 0 ? (
        <p className="text-meta text-muted-foreground">and {plural(more, "more file")}</p>
      ) : null}
      <Button type="button" variant="outline" className="self-start" onClick={onReview}>
        <FileSearchIcon aria-hidden="true" data-icon="inline-start" />
        Review {plural(gate.changes.length, "file")}
      </Button>
    </section>
  );
}
