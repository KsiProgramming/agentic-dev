"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDownIcon, CirclePauseIcon, ListTreeIcon, RadioIcon, TableIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { useConsoleWaiting } from "@/components/shell/attention";
import { EmptyState, ErrorState } from "@/components/states";
import type { RunStatus } from "@/components/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { pendingGate, type PendingGate } from "../gates";
import { displayStatus } from "../status";
import { badgeStatus, statusLabel } from "../summaries";
import { usageOfRun } from "../cost";
import { buildTimeline, stepsUsage, type Step } from "../timeline";
import type { ReceivedRunEvent, StreamStatus } from "../types";
import { useFollowScroll } from "../use-follow-scroll";
import { useNow } from "../use-now";
import { runDetailKey, useRunDetail, type RunDetail } from "../use-run-detail";
import { useRunEvents } from "../use-run-events";
import { currentActivity } from "./activity";
import { ActivityLine } from "./activity-line";
import { ApprovalDock, DOCK_ID } from "./approval-dock";
import { canRerun, RerunButton } from "../rerun";
import { CancelRunButton } from "./cancel-run-button";
import { RawEvents } from "./raw-events";
import { RunHeader, type HeaderFacts } from "./run-header";
import { StepList } from "./step-view";

type Tab = "timeline" | "raw";

/** The run console. Retry reconnects by mounting a fresh event stream. */
export function RunConsole({ runId, baseUrl }: { runId: string; baseUrl?: string }) {
  const [attempt, setAttempt] = useState(0);
  return (
    <Console
      key={attempt}
      runId={runId}
      baseUrl={baseUrl}
      onRetry={() => setAttempt((n) => n + 1)}
    />
  );
}

/** What the header says: from the event stream once it has events, from the summary before. */
export function headerFacts(
  stream: StreamStatus,
  events: ReceivedRunEvent[],
  gate: PendingGate | null,
  run: RunDetail | null | undefined,
  timeline: {
    steps: Step[];
    workflowName: string | null;
    startedAt: string | null;
    endedAt: string | null;
  },
  prUrl: string | null,
  now: number,
): HeaderFacts {
  const status =
    run && events.length === 0 && (stream === "connecting" || stream === "live")
      ? { status: badgeStatus(run.status), label: statusLabel(run.status) }
      : displayStatus(stream, gate !== null);
  const startedAt = timeline.startedAt ?? run?.started_at ?? null;
  const endedAt = timeline.endedAt ?? run?.finished_at ?? null;
  const durationMs =
    startedAt === null
      ? null
      : Math.max(0, (endedAt ? Date.parse(endedAt) : now) - Date.parse(startedAt));
  return {
    status,
    workflowName: run?.workflow.name ?? timeline.workflowName,
    startedAt,
    durationMs,
    prUrl: prUrl ?? run?.pr_url ?? null,
    // Added up live from the events; the summary's totals until they arrive.
    usage: stepsUsage(timeline.steps) ?? (run?.usage.input_tokens ? usageOfRun(run.usage) : null),
  };
}

/** A run can be cancelled until it has ended. */
function canCancel(status: RunStatus): boolean {
  return status === "queued" || status === "running" || status === "waiting";
}

function lastPullRequest(steps: Step[]): string | null {
  let url: string | null = null;
  const visit = (list: Step[]) => {
    for (const step of list) {
      url = step.prUrl ?? url;
      for (const iteration of step.iterations ?? []) visit(iteration.steps);
      for (const item of step.items ?? []) visit(item.steps);
    }
  };
  visit(steps);
  return url;
}

/** In the waiting step: the decision is made in the dock at the bottom of the page. */
function WaitingMarker() {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[13px]" data-testid="waiting-marker">
      <CirclePauseIcon aria-hidden="true" className="size-4 text-status-waiting" />
      <span className="font-medium">Waiting for approval</span>
      <Button
        type="button"
        variant="link"
        size="sm"
        className="h-auto px-0"
        onClick={() => document.getElementById(DOCK_ID)?.focus()}
      >
        Go to the decision
      </Button>
    </div>
  );
}

function Console({
  runId,
  baseUrl,
  onRetry,
}: {
  runId: string;
  baseUrl?: string;
  onRetry: () => void;
}) {
  const { events, status } = useRunEvents(runId, baseUrl);
  const detail = useRunDetail(runId, baseUrl);
  const client = useQueryClient();
  const timeline = useMemo(() => buildTimeline(events), [events]);
  const gate = status === "live" ? pendingGate(events) : null;
  const prUrl = lastPullRequest(timeline.steps);
  const live = status === "connecting" || status === "live";
  const now = useNow(1000, live);
  const follow = useFollowScroll(events.length, status === "live");
  useConsoleWaiting(gate !== null);

  // The summary (repo, PR, failure reason) moves on with the run: fetch it again when it does.
  useEffect(() => {
    void client.invalidateQueries({ queryKey: runDetailKey(runId) });
  }, [client, runId, status, gate?.nodeId, prUrl]);

  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab: Tab = params.get("tab") === "raw" ? "raw" : "timeline";
  const setTab = (next: string) => {
    const query = new URLSearchParams(params);
    if (next === "raw") query.set("tab", "raw");
    else query.delete("tab");
    const search = query.toString();
    router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
  };

  if (status === "not_found" || detail.data === null) {
    // Every page has one heading, a missing run too.
    return (
      <section className="flex flex-col gap-6">
        <PageHeader title="Run" />
        <ErrorState message="Run not found." />
      </section>
    );
  }

  const run = detail.data;
  const facts = headerFacts(status, events, gate, run, timeline, prUrl, now);
  const activity = status === "live" && !gate ? currentActivity(timeline) : null;
  const failure = run?.status === "failed" ? run.failure_reason : null;

  return (
    <section className="flex flex-col gap-6">
      <RunHeader
        runId={runId}
        run={run}
        facts={facts}
        now={now}
        actions={
          canCancel(facts.status.status) ? (
            <CancelRunButton runId={runId} baseUrl={baseUrl} />
          ) : canRerun(facts.status.status) && !live ? (
            <RerunButton runId={runId} status={facts.status.status} baseUrl={baseUrl} />
          ) : null
        }
      />

      {status === "error" ? (
        <ErrorState message="Lost the connection to the event stream." onRetry={onRetry} />
      ) : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Run views">
          <TabsTrigger value="timeline">
            <ListTreeIcon aria-hidden="true" />
            Timeline
          </TabsTrigger>
          <TabsTrigger value="raw">
            <TableIcon aria-hidden="true" />
            Raw events
          </TabsTrigger>
        </TabsList>

        <TabsContent value="timeline" className="flex flex-col gap-5 pt-2">
          {failure ? (
            <Alert variant="destructive">
              <AlertDescription className="break-words">{failure}</AlertDescription>
            </Alert>
          ) : null}
          {timeline.steps.length === 0 ? (
            live ? (
              <EmptyState icon={RadioIcon} message="Waiting for the run to start…" />
            ) : (
              <EmptyState icon={RadioIcon} message="This run ended before its first step." />
            )
          ) : (
            <StepList
              steps={timeline.steps}
              options={{
                now,
                extra: (step) =>
                  gate && step.id === gate.nodeId && step.status === "waiting" ? (
                    <WaitingMarker />
                  ) : null,
              }}
            />
          )}
          {activity ? <ActivityLine activity={activity} /> : null}
        </TabsContent>

        <TabsContent value="raw" className="pt-2">
          {events.length === 0 ? (
            <EmptyState icon={RadioIcon} message="Waiting for events…" />
          ) : (
            <RawEvents events={events} />
          )}
        </TabsContent>
      </Tabs>

      {/* Announced once when a gate starts waiting; the dock itself never takes focus. */}
      <div aria-live="polite" className="sr-only">
        {gate ? `Approval needed: ${gate.title}` : ""}
      </div>
      {gate ? <ApprovalDock key={gate.nodeId} runId={runId} gate={gate} baseUrl={baseUrl} /> : null}

      {follow.behind ? (
        <div className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--dock-height,0px)+1.5rem)] z-40 flex justify-center">
          <Button
            type="button"
            size="sm"
            className="pointer-events-auto rounded-full shadow-sm"
            onClick={follow.jump}
          >
            <ArrowDownIcon aria-hidden="true" data-icon="inline-start" />
            Jump to latest
          </Button>
        </div>
      ) : null}
    </section>
  );
}
