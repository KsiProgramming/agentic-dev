"use client";

import { CircleAlertIcon, CirclePauseIcon, HourglassIcon, TimerOffIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import { ExpiresIn, WaitingTime } from "@/components/display";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import type { PendingGate } from "../gates";
import { DOCK_ID } from "./approval-dock";
import { ApproveButton, GateDecisionDialogs, RejectButton } from "./decision-controls";
import { useGateDecision } from "./use-gate-decision";
import type { StepRow } from "./step-entries";

/** What needs the user, under the run's figures: why it failed, the gate it waits at, or why its
 * approval expired. At most one: a run is in one of these states at a time. */
export type BannerState =
  | { kind: "failed"; step: StepRow | null; reason: string }
  | { kind: "waiting"; gate: PendingGate; runId: string }
  | { kind: "paused"; gate: PendingGate; runId: string; step: StepRow | null }
  | { kind: "answers"; gate: PendingGate; runId: string; waitingMs: number }
  | { kind: "expired"; reason: string };

export function RunBanner({
  banner,
  onGoToStep,
  baseUrl,
}: {
  banner: BannerState;
  onGoToStep: (key: string) => void;
  baseUrl?: string;
}) {
  if (banner.kind === "answers") return <AnswersBanner banner={banner} baseUrl={baseUrl} />;
  if (banner.kind === "paused") {
    return <PausedBanner banner={banner} onGoToStep={onGoToStep} baseUrl={baseUrl} />;
  }
  if (banner.kind === "failed") {
    return (
      <Alert variant="destructive" data-testid="run-banner" data-kind="failed">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle className="break-words">
          {banner.step ? (
            <>
              Failed at <span className="font-mono">{banner.step.name}</span>
            </>
          ) : (
            "The run failed"
          )}
        </AlertTitle>
        <AlertDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="min-w-0 break-words">{banner.reason}</span>
          {banner.step ? (
            <Button
              type="button"
              variant="link"
              size="sm"
              onClick={() => onGoToStep(banner.step!.key)}
            >
              Go to step
            </Button>
          ) : null}
        </AlertDescription>
      </Alert>
    );
  }
  if (banner.kind === "waiting") {
    const { gate } = banner;
    return (
      // Not an alert: the page's live region already announces the gate once.
      <Alert variant="waiting" role={undefined} data-testid="run-banner" data-kind="waiting">
        <CirclePauseIcon aria-hidden="true" />
        <AlertTitle className="flex flex-wrap items-center gap-x-2 break-words">
          <span>Needs approval: {gate.title}</span>
          {gate.expiresAt ? (
            <ExpiresIn iso={gate.expiresAt} className="font-normal text-status-waiting" />
          ) : null}
        </AlertTitle>
        <AlertDescription className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={() => document.getElementById(DOCK_ID)?.focus()}
          >
            Review
          </Button>
          <Link
            href={`/inbox?run=${banner.runId}`}
            className="text-meta text-foreground underline-offset-4 hover:underline"
          >
            Open in Inbox
          </Link>
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert role={undefined} data-testid="run-banner" data-kind="expired">
      <TimerOffIcon aria-hidden="true" />
      <AlertDescription className="break-words">
        {banner.reason}: nobody approved or rejected the gate before its time to live ran out.
      </AlertDescription>
    </Alert>
  );
}

/** A run a circuit breaker paused (13.7): why, when the pause expires, and the two things a
 * person can do, Resume and Cancel run (the dock at the bottom has them too). */
function PausedBanner({
  banner,
  onGoToStep,
  baseUrl,
}: {
  banner: Extract<BannerState, { kind: "paused" }>;
  onGoToStep: (key: string) => void;
  baseUrl?: string;
}) {
  const { gate, runId, step } = banner;
  const decision = useGateDecision({ runId, gate, baseUrl, shortcuts: false });
  return (
    <Alert variant="waiting" role={undefined} data-testid="run-banner" data-kind="paused">
      <CirclePauseIcon aria-hidden="true" />
      <AlertTitle className="flex flex-wrap items-center gap-x-2 break-words">
        <span>Paused by a circuit breaker: {gate.breaker?.reason}</span>
        {gate.expiresAt ? (
          <ExpiresIn iso={gate.expiresAt} className="font-normal text-status-waiting" />
        ) : null}
      </AlertTitle>
      <AlertDescription className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {step ? (
          <Button type="button" variant="link" size="sm" onClick={() => onGoToStep(step.key)}>
            Go to step
          </Button>
        ) : null}
        {decision.sent ? (
          <span role="status" className="font-medium">
            {decision.sent === "approve" ? "Resumed" : "Cancelled"}. The run carries on shortly.
          </span>
        ) : (
          <>
            <ApproveButton decision={decision} shortcut={false} />
            <RejectButton decision={decision} shortcut={false} />
          </>
        )}
        {decision.error && !decision.rejecting ? (
          <span className="text-status-failed">{decision.error}</span>
        ) : null}
      </AlertDescription>
      <GateDecisionDialogs decision={decision} />
    </Alert>
  );
}

/** A run that asked the team a question and waits for the answer (7.9): it builds nothing until
 * someone other than the platform comments on the issue, or "Check now" finds one. */
function AnswersBanner({
  banner,
  baseUrl,
}: {
  banner: Extract<BannerState, { kind: "answers" }>;
  baseUrl?: string;
}) {
  const { gate, runId, waitingMs } = banner;
  const [checking, setChecking] = useState(false);
  const issue = gate.waitFor?.issueKey ?? "the issue";

  async function check() {
    setChecking(true);
    try {
      const { data, response } = await createApiClient(baseUrl).POST(
        "/runs/{run_id}/answers/check",
        { params: { path: { run_id: runId } } },
      );
      if (data) {
        toast[data.found ? "success" : "message"](
          data.found ? "An answer arrived: the run goes on." : "No answer yet.",
        );
      } else if (response.status === 409) {
        toast.error("The run is not waiting for an answer any more.");
      } else {
        toast.error(`Jira could not be checked (HTTP ${response.status}).`);
      }
    } catch {
      toast.error("Could not reach the API.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <Alert variant="waiting" role={undefined} data-testid="run-banner" data-kind="answers">
      <HourglassIcon aria-hidden="true" />
      <AlertTitle className="flex flex-wrap items-center gap-x-2 break-words">
        <StatusBadge status="waiting" />
        <span>Waiting for answers on {issue}</span>
        <WaitingTime ms={waitingMs} live className="font-normal text-status-waiting" />
        {gate.expiresAt ? (
          <ExpiresIn iso={gate.expiresAt} className="font-normal text-status-waiting" />
        ) : null}
      </AlertTitle>
      <AlertDescription className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="min-w-0 break-words">
          The questions are posted. Nothing is built until someone other than the platform answers
          on the issue.
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={checking}
          onClick={() => void check()}
        >
          {checking ? "Checking…" : "Check now"}
        </Button>
        {gate.waitFor?.issueUrl ? (
          <a
            href={gate.waitFor.issueUrl}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-meta text-foreground underline-offset-4 hover:underline"
          >
            Open {issue} in Jira
          </a>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
