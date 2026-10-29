"use client";

import { EllipsisIcon, ExternalLinkIcon, GitBranchIcon, RotateCcwIcon } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";

import { Duration, IdChip, Money, RelativeTime, shortId, WaitingTime } from "@/components/display";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { usageOfRun } from "./cost";
import { groupRuns } from "./date-groups";
import { canRerun, RerunOf, useRerun } from "./rerun";
import {
  badgeStatus,
  expiredLabel,
  isLive,
  repoLabel,
  runTimes,
  wallClockLine,
  type RunSummary,
} from "./summaries";

/** A link over its whole row or card; other links in it sit above it (`relative z-10`). */
const STRETCHED =
  "rounded-sm font-medium outline-none after:absolute after:inset-0 after:content-[''] focus-visible:ring-3 focus-visible:ring-ring/50";

function PrLink({ url }: { url: string }) {
  const number = /\/pull\/(\d+)/.exec(url)?.[1];
  const label = number ? `#${number}` : "PR";
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Pull request ${label} (opens in a new tab)`}
      className="relative z-10 inline-flex items-center gap-1 rounded-sm text-foreground tabular-nums outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {label}
      <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
    </a>
  );
}

/** The run's status. A waiting run's badge links to its review on the console. */
function RunStatusBadge({ run }: { run: RunSummary }) {
  const badge = <StatusBadge status={badgeStatus(run.status)} label={expiredLabel(run)} />;
  if (run.status !== "waiting") return badge;
  return (
    <Link
      href={`/runs/${run.id}`}
      className="relative z-10 w-fit rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {badge}
      <span className="sr-only">
        : review {run.workflow.name} {shortId(run.id)}
      </span>
    </Link>
  );
}

/** What started the run: "Manual", "API" or "Rerun of <id>". */
function Trigger({ run }: { run: RunSummary }) {
  if (run.rerun_of) return <RerunOf runId={run.rerun_of} />;
  return (
    <span>{run.trigger === "manual" ? "Manual" : run.trigger === "api" ? "API" : "Rerun"}</span>
  );
}

/** The workflow's name, opening the run; under it the run's short id and what started it. */
function RunName({ run, className }: { run: RunSummary; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col", className)}>
      <Link href={`/runs/${run.id}`} className={cn(STRETCHED, "truncate")}>
        {run.workflow.name}
      </Link>
      <span className="flex items-center gap-1.5 text-caption text-muted-foreground">
        <IdChip id={run.id} label="run id" focusable={false} className={IN_ROW} />
        <span aria-hidden="true">·</span>
        <Trigger run={run} />
      </span>
    </div>
  );
}

/** A run's other actions, in a "⋯" menu: Rerun, for an ended run. */
function RunMenu({ run, baseUrl }: { run: RunSummary; baseUrl?: string }) {
  const rerun = useRerun({ workspaceId: run.workspace_id, baseUrl });
  if (!canRerun(badgeStatus(run.status))) return null;
  // Not modal: a modal menu hides the rest of the page with `aria-hidden` while its links and
  // buttons stay focusable (axe: aria-hidden-focus). Focus still moves into the menu, and Escape
  // or a click outside closes it.
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="relative z-10"
          disabled={rerun.isPending}
          aria-label={`Actions for ${run.workflow.name} ${shortId(run.id)}`}
        >
          <EllipsisIcon aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => rerun.mutate(run.id)}>
          <RotateCcwIcon aria-hidden="true" />
          Rerun
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Values in a row sit above its stretched link, so their tooltips open on hover. They take no
 * focus: the row's link and actions are its tab stops. */
const IN_ROW = "relative z-10";

/** When the run started; the wall clock (start to end) is only in its tooltip. */
function Started({ run, now }: { run: RunSummary; now: number }) {
  return (
    <RelativeTime
      iso={run.started_at ?? run.created_at}
      now={now}
      detail={wallClockLine(runTimes(run, now).wallMs, isLive(run.status))}
      focusable={false}
      className={`${IN_ROW} text-foreground-secondary`}
    />
  );
}

/** The run's duration, the time it worked, then the time it waited at gates on its own:
 * "2m 00s · waited 1h 00m". */
function RunTime({ run, now }: { run: RunSummary; now: number }) {
  const { activeMs, waitingMs } = runTimes(run, now);
  const waiting = run.status === "waiting";
  return (
    <span data-testid="run-time" className="text-foreground-secondary tabular-nums">
      <Duration ms={activeMs} />
      {waitingMs > 0 || waiting ? (
        <span className={waiting ? "text-status-waiting" : "text-foreground-secondary"}>
          {" · "}
          <WaitingTime ms={waitingMs} live={waiting} />
        </span>
      ) : null}
    </span>
  );
}

/** What the run cost so far: "—" before any usage is logged; "$0.00" for a run that ended
 * without calling a model (only tool steps), which cost nothing rather than nothing yet. */
function Cost({ run }: { run: RunSummary }) {
  const usage = usageOfRun(run.usage);
  if (usage.inputTokens + usage.outputTokens === 0) {
    if (!isLive(run.status) && run.finished_at && run.usage.cost_complete) {
      return (
        <span title="No model calls" className="text-foreground-secondary">
          <Money data-testid="run-cost" usd={0} />
        </span>
      );
    }
    return <span className="text-placeholder">—</span>;
  }
  return (
    <Money
      data-testid="run-cost"
      usage={usage}
      focusable={false}
      className={`${IN_ROW} text-foreground-secondary`}
    />
  );
}

/** The repo (mono), with the branch the run works on under it when it is not the default. */
function Repo({ run }: { run: RunSummary }) {
  if (!run.repo) return <span className="text-placeholder">—</span>;
  return (
    <div className="flex max-w-64 min-w-0 flex-col">
      <span
        title={run.repo.url}
        className="truncate font-mono text-caption text-foreground-secondary"
      >
        {repoLabel(run.repo.url)}
      </span>
      {run.branch ? (
        <span className="flex min-w-0 items-center gap-1 text-caption text-muted-foreground">
          <GitBranchIcon aria-hidden="true" className="size-3 shrink-0" />
          <span className="sr-only">Branch </span>
          <span className="truncate font-mono">{run.branch}</span>
        </span>
      ) : null}
    </div>
  );
}

/** A date header sticks under the top bar (`h-14`) while its rows scroll by. */
const DATE_HEADER =
  "sticky top-12 z-20 bg-background text-caption font-medium text-muted-foreground";

/** Runs as a table, from `md` (768 px), under their date headers. A row opens the run. From
 * `lg` the table fits the page, so it drops its scroll box and the headers stick. */
export function RunsTable({
  runs,
  now,
  label,
  baseUrl,
}: {
  runs: RunSummary[];
  now: number;
  label: string;
  baseUrl?: string;
}) {
  return (
    <Table aria-label={label} containerClassName="lg:overflow-x-visible">
      <TableHeader>
        <TableRow>
          <TableHead>Status</TableHead>
          <TableHead>Run</TableHead>
          <TableHead>Repository</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead className="text-right">Cost</TableHead>
          <TableHead>Pull request</TableHead>
          <TableHead className="w-10">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      {groupRuns(runs, now).map(({ group, runs: grouped }) => (
        <TableBody key={group} data-date-group={group}>
          <TableRow className="hover:bg-transparent">
            <TableHead colSpan={8} scope="rowgroup" className={cn(DATE_HEADER, "h-8")}>
              {group}
            </TableHead>
          </TableRow>
          {grouped.map((run) => (
            <TableRow key={run.id} data-run-id={run.id} className="relative">
              <TableCell>
                <RunStatusBadge run={run} />
              </TableCell>
              <TableCell className="max-w-72">
                <RunName run={run} />
              </TableCell>
              <TableCell>
                <Repo run={run} />
              </TableCell>
              <TableCell>
                <Started run={run} now={now} />
              </TableCell>
              <TableCell>
                <RunTime run={run} now={now} />
              </TableCell>
              <TableCell className="text-right">
                <Cost run={run} />
              </TableCell>
              <TableCell>
                {run.pr_url ? (
                  <PrLink url={run.pr_url} />
                ) : (
                  <span className="text-placeholder">—</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <RunMenu run={run} baseUrl={baseUrl} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      ))}
    </Table>
  );
}

/** One run as a card, below `md`. The card opens the run. */
export function RunCard({ run, now, baseUrl }: { run: RunSummary; now: number; baseUrl?: string }) {
  return (
    <Card size="sm" data-run-id={run.id} className="relative px-3 hover:bg-muted/50">
      <div className="flex items-start justify-between gap-2">
        <RunName run={run} />
        <div className="flex shrink-0 items-center gap-1">
          <RunStatusBadge run={run} />
          <RunMenu run={run} baseUrl={baseUrl} />
        </div>
      </div>
      <Repo run={run} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-foreground-secondary">
        <Started run={run} now={now} />
        <span>
          <span className="sr-only">Duration </span>
          <RunTime run={run} now={now} />
        </span>
        <span>
          <span className="sr-only">Cost </span>
          <Cost run={run} />
        </span>
        {run.pr_url ? <PrLink url={run.pr_url} /> : null}
      </div>
    </Card>
  );
}

/** Runs as a table from `md` and as cards below, grouped under date headers. */
export function RunsList({
  runs,
  now,
  label,
  baseUrl,
}: {
  runs: RunSummary[];
  now: number;
  label: string;
  baseUrl?: string;
}) {
  return (
    <>
      <div className="hidden md:block">
        <RunsTable runs={runs} now={now} label={label} baseUrl={baseUrl} />
      </div>
      <div className="flex flex-col gap-2 md:hidden">
        {groupRuns(runs, now).map(({ group, runs: grouped }) => (
          <Fragment key={group}>
            <h3 data-date-group={group} className={cn(DATE_HEADER, "py-1")}>
              {group}
            </h3>
            <ul aria-label={`${label}, ${group}`} className="flex flex-col gap-2">
              {grouped.map((run) => (
                <li key={run.id}>
                  <RunCard run={run} now={now} baseUrl={baseUrl} />
                </li>
              ))}
            </ul>
          </Fragment>
        ))}
      </div>
    </>
  );
}
