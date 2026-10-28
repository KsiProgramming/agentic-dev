"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownIcon,
  CirclePauseIcon,
  FilesIcon,
  ListTreeIcon,
  NetworkIcon,
  RadioIcon,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { useConsoleWaiting } from "@/components/shell/attention";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import type { RunStatus } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { ArtifactsView } from "../artifacts/artifacts-view";
import { pendingGate, type PendingGate } from "../gates";
import { RunGraph } from "../graph/run-graph";
import { allSpecNodes, type NodeKind } from "../graph/spec-graph";
import { displayStatus } from "../status";
import { badgeStatus, runTimes, statusLabel, wallClockLine } from "../summaries";
import { usageOfRun } from "../cost";
import { specParents } from "../spec-parents";
import { buildTimeline, clockAt, stepsUsage, type Step, type Timeline } from "../timeline";
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
import { RunBanner, type BannerState } from "./run-banner";
import { RunHeader, type HeaderFacts } from "./run-header";
import { stepsProgress } from "./run-stats";
import { RunTiles } from "./run-tiles";
import {
  defaultEntry,
  failingEntry,
  findEntry,
  stepEntries,
  stepRows,
  type StepRow,
} from "./step-entries";
import { guessKind, StepList } from "./step-list";
import { STEP_TABS, StepPanel, type StepTab } from "./step-panel";

type View = "list" | "graph" | "artifacts";

/** From 1280 px the step list and the selected step sit side by side. */
const XL_UP = "(min-width: 1280px)";
const PANEL_ID = "step-panel";

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
  timeline: Timeline,
  prUrl: string | null,
  now: number,
): HeaderFacts {
  const shown =
    run && events.length === 0 && (stream === "connecting" || stream === "live")
      ? { status: badgeStatus(run.status), label: statusLabel(run.status) }
      : displayStatus(stream, gate !== null);
  // A run whose gate expired is cancelled, worded "Expired" (in Cancelled's grey).
  const status =
    shown.status === "cancelled" && (timeline.expired || run?.expired)
      ? { ...shown, label: "Expired" }
      : shown;
  const startedAt = timeline.startedAt ?? run?.started_at ?? null;
  const endedAt = timeline.endedAt ?? run?.finished_at ?? null;
  // Active and waiting time from the events once the run's start is among them, the summary's
  // before; the wall clock only for the start time's tooltip.
  const times =
    timeline.startedAt !== null
      ? clockAt(timeline.clock, now)
      : run
        ? runTimes(run, now)
        : { activeMs: null, waitingMs: 0 };
  const live = endedAt === null && startedAt !== null;
  const wallMs =
    startedAt === null
      ? null
      : Math.max(0, (endedAt ? Date.parse(endedAt) : now) - Date.parse(startedAt));
  return {
    status,
    workflowName: run?.workflow.name ?? timeline.workflowName,
    startedAt,
    activeMs: times.activeMs,
    waitingMs: times.waitingMs,
    waitingLive: events.length > 0 ? gate !== null : run?.status === "waiting",
    wallClock: wallClockLine(wallMs, live),
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
      for (const branch of step.branches ?? []) visit(branch.steps);
      visit(step.router?.steps ?? []);
    }
  };
  visit(steps);
  return url;
}

/** In the waiting gate's output: the decision is made in the dock at the bottom of the page. */
function WaitingMarker() {
  return (
    <div className="flex flex-wrap items-center gap-2 text-meta" data-testid="waiting-marker">
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

/** The console's place in the URL: the step list, the graph or the run's artifacts, the selected
 * step and its tab. Links from before 11.6 still open: `?tab=graph` is the graph, `?tab=raw` the
 * Events tab. */
function useConsoleParams() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const asked = params.get("tab");
  const named = params.get("view");
  const view: View =
    named === "graph" || asked === "graph" ? "graph" : named === "artifacts" ? "artifacts" : "list";
  const tab: StepTab =
    asked === "raw" ? "events" : (STEP_TABS.find((t) => t === asked) ?? "output");
  const step = params.get("step");
  const update = useCallback(
    (changes: Record<string, string | null>) => {
      const query = new URLSearchParams(params);
      const old = query.get("tab");
      if (old === "graph") query.set("view", "graph");
      if (old === "raw") query.set("tab", "events");
      if (old === "graph" || old === "timeline") query.delete("tab");
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) query.delete(key);
        else query.set(key, value);
      }
      const search = query.toString();
      router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );
  return { view, tab, step, update };
}

/** Why the run failed, from its `run_failed` event, before the summary has it. */
function runFailure(events: ReceivedRunEvent[]): string | null {
  const error = events.findLast((e) => e.type === "run_failed")?.payload?.error;
  return typeof error === "string" && error ? error : null;
}

/** The step a click on graph node `nodeId` shows: the run of it that needs attention first. */
function rowForNode(rows: StepRow[], nodeId: string): StepRow | null {
  const runs = rows.filter((r) => r.step.id === nodeId);
  for (const status of ["failed", "waiting", "running", "cancelled"] as const) {
    const found = runs.find((r) => r.step.status === status);
    if (found) return found;
  }
  return runs.at(-1) ?? null;
}

/** Shows the selected step: beside the list from 1280 px, below it under that, so it is
 * scrolled to. */
function revealPanel(focus: boolean) {
  setTimeout(() => {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;
    if (!window.matchMedia?.(XL_UP).matches) panel.scrollIntoView?.({ block: "start" });
    if (focus) panel.focus({ preventScroll: true });
  }, 0);
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
  const spec = detail.data?.spec ?? null;
  // Nested nodes are placed by the spec once it loaded (4.6): their tags alone are ambiguous.
  const parents = useMemo(() => (spec ? specParents(spec.root) : null), [spec]);
  const timeline = useMemo(() => buildTimeline(events, parents), [events, parents]);
  const entries = useMemo(() => stepEntries(timeline.steps), [timeline]);
  const rows = useMemo(() => stepRows(entries), [entries]);
  const gate = status === "live" ? pendingGate(events) : null;
  const prUrl = lastPullRequest(timeline.steps);
  const written = events.filter((e) => e.type === "artifact_written").length;
  const live = status === "connecting" || status === "live";
  const now = useNow(1000, live);
  const follow = useFollowScroll(events.length, status === "live");
  const { view, tab, step: asked, update } = useConsoleParams();
  useConsoleWaiting(gate !== null);

  // The summary (repo, PR, failure reason) moves on with the run: fetch it again when it does.
  useEffect(() => {
    void client.invalidateQueries({ queryKey: runDetailKey(runId) });
  }, [client, runId, status, gate?.nodeId, prUrl]);

  const kinds = useMemo(
    () => new Map<string, NodeKind>(spec ? allSpecNodes(spec).map((n) => [n.id, n.type]) : []),
    [spec],
  );
  const kindOf = useCallback((nodeId: string) => kinds.get(nodeId) ?? null, [kinds]);

  const select = useCallback(
    (key: string) => {
      update({ step: key });
      revealPanel(false);
    },
    [update],
  );
  const openNode = useCallback(
    (nodeId: string) => {
      const row = rowForNode(rows, nodeId);
      if (row) select(row.key);
    },
    [rows, select],
  );

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
  // The step the URL names; else the running one while live (followed as the run moves), the
  // waiting gate, the failing step or the last agent's answer.
  const selected = findEntry(entries, asked) ?? defaultEntry(entries, live);
  const kind = selected ? (kindOf(selected.step.id) ?? guessKind(selected.step)) : null;

  let banner: BannerState | null = null;
  if (facts.status.status === "failed") {
    const failing = failingEntry(entries);
    banner = {
      kind: "failed",
      step: failing,
      reason:
        failing?.step.error ??
        run?.failure_reason ??
        runFailure(events) ??
        "The run failed for a reason it did not log.",
    };
  } else if (gate) {
    banner = { kind: "waiting", gate, runId };
  } else if (facts.status.label === "Expired") {
    // Why an expired run ended; a user's cancel needs no explanation.
    banner = {
      kind: "expired",
      reason: timeline.cancelReason ?? run?.cancel_reason ?? "Approval expired",
    };
  }

  return (
    <section className="flex flex-col gap-6">
      <RunHeader
        runId={runId}
        run={run}
        facts={facts}
        now={now}
        events={events}
        actions={
          canCancel(facts.status.status) ? (
            <CancelRunButton runId={runId} baseUrl={baseUrl} />
          ) : canRerun(facts.status.status) && !live ? (
            <RerunButton runId={runId} status={facts.status.status} baseUrl={baseUrl} />
          ) : null
        }
      />

      <RunTiles
        facts={facts}
        budget={run?.usage.budget_usd ?? null}
        progress={spec ? stepsProgress(spec, timeline.steps) : null}
        createdRepo={rows.find((r) => r.step.createdRepo)?.step.createdRepo ?? null}
      />

      {banner ? (
        <RunBanner
          banner={banner}
          onGoToStep={(key) => {
            update({ step: key, tab: null });
            revealPanel(true);
          }}
        />
      ) : null}

      {status === "error" ? (
        <ErrorState message="Lost the connection to the event stream." onRetry={onRetry} />
      ) : null}

      <div className="flex min-w-0 flex-col gap-6 xl:grid xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] xl:items-start">
        <Tabs
          value={view}
          onValueChange={(next) => update({ view: next === "list" ? null : next })}
          className="min-w-0"
        >
          <TabsList aria-label="Run views">
            <TabsTrigger value="list">
              <ListTreeIcon aria-hidden="true" />
              Steps
            </TabsTrigger>
            <TabsTrigger value="graph">
              <NetworkIcon aria-hidden="true" />
              Graph
            </TabsTrigger>
            <TabsTrigger value="artifacts">
              <FilesIcon aria-hidden="true" />
              Artifacts
            </TabsTrigger>
          </TabsList>

          <TabsContent value="list" className="pt-2">
            {entries.length === 0 ? (
              live ? (
                <EmptyState icon={RadioIcon} message="Waiting for the run to start…" />
              ) : (
                <EmptyState icon={RadioIcon} message="This run ended before its first step." />
              )
            ) : (
              <StepList
                entries={entries}
                selected={selected?.key ?? null}
                now={now}
                kindOf={kindOf}
                onSelect={select}
                footer={activity ? <ActivityLine activity={activity} /> : null}
              />
            )}
          </TabsContent>

          <TabsContent value="graph" className="pt-2">
            {spec ? (
              <RunGraph
                spec={spec}
                steps={timeline.steps}
                selected={selected?.step.id ?? null}
                onOpen={openNode}
              />
            ) : detail.isError ? (
              <ErrorState message="Could not load the workflow." onRetry={() => detail.refetch()} />
            ) : (
              <LoadingState label="Loading the workflow…" />
            )}
          </TabsContent>

          <TabsContent value="artifacts" className="pt-2">
            <ArtifactsView
              runId={runId}
              written={written}
              live={live}
              now={now}
              onOpenStep={openNode}
              baseUrl={baseUrl}
            />
          </TabsContent>
        </Tabs>

        {selected && kind ? (
          <div id={PANEL_ID} tabIndex={-1} className="min-w-0 scroll-mt-20 outline-none">
            <StepPanel
              runId={runId}
              baseUrl={baseUrl}
              row={selected}
              kind={kind}
              entries={entries}
              spec={spec}
              runInput={run?.input ?? null}
              first={rows[0]?.key === selected.key}
              events={events}
              now={now}
              tab={tab}
              onTab={(next) => update({ tab: next === "output" ? null : next })}
              onSelect={select}
              extra={
                gate && selected.step.id === gate.nodeId && selected.step.status === "waiting" ? (
                  <WaitingMarker />
                ) : null
              }
            />
          </div>
        ) : null}
      </div>

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
