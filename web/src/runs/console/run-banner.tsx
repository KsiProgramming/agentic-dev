"use client";

import { CircleAlertIcon, CirclePauseIcon, TimerOffIcon } from "lucide-react";
import Link from "next/link";

import { ExpiresIn } from "@/components/display";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import type { PendingGate } from "../gates";
import { DOCK_ID } from "./approval-dock";
import type { StepRow } from "./step-entries";

/** What needs the user, under the run's figures: why it failed, the gate it waits at, or why its
 * approval expired. At most one: a run is in one of these states at a time. */
export type BannerState =
  | { kind: "failed"; step: StepRow | null; reason: string }
  | { kind: "waiting"; gate: PendingGate; runId: string }
  | { kind: "expired"; reason: string };

export function RunBanner({
  banner,
  onGoToStep,
}: {
  banner: BannerState;
  onGoToStep: (key: string) => void;
}) {
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
