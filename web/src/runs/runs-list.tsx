"use client";

import { EllipsisIcon, ExternalLinkIcon, RotateCcwIcon } from "lucide-react";
import Link from "next/link";

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

import { canRerun, RerunOf, useRerun } from "./rerun";
import {
  badgeStatus,
  formatAbsolute,
  formatDuration,
  formatRelative,
  repoLabel,
  runDurationMs,
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
      className="relative z-10 inline-flex items-center gap-1 rounded-sm text-primary tabular-nums outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {label}
      <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
    </a>
  );
}

/** A waiting run's way to its decision: the console, where the gate is reviewed. */
function ReviewLink({ run }: { run: RunSummary }) {
  if (run.status !== "waiting") return null;
  return (
    <Button asChild size="xs" variant="outline" className="relative z-10">
      <Link href={`/runs/${run.id}`}>
        Review
        <span className="sr-only"> {run.workflow.name}</span>
      </Link>
    </Button>
  );
}

/** A run's other actions, in a "⋯" menu: Rerun, for an ended run. */
function RunMenu({ run, baseUrl }: { run: RunSummary; baseUrl?: string }) {
  const rerun = useRerun({ workspaceId: run.workspace_id, baseUrl });
  if (!canRerun(badgeStatus(run.status))) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="relative z-10"
          disabled={rerun.isPending}
          aria-label={`Actions for ${run.workflow.name} ${run.id.slice(0, 8)}`}
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

function Started({ run, now }: { run: RunSummary; now: number }) {
  const at = run.started_at ?? run.created_at;
  return (
    <time dateTime={at} title={formatAbsolute(at)} className="tabular-nums">
      {formatRelative(at, now)}
    </time>
  );
}

function Duration({ run, now }: { run: RunSummary; now: number }) {
  const ms = runDurationMs(run, now);
  return <span className="tabular-nums">{ms === null ? "—" : formatDuration(ms)}</span>;
}

function Repo({ run }: { run: RunSummary }) {
  if (!run.repo) return <span className="text-muted-foreground">—</span>;
  return (
    <span title={run.repo.url} className="block max-w-64 truncate font-mono text-xs">
      {repoLabel(run.repo.url)}
    </span>
  );
}

/** Runs as a table, from `md` (768 px). A row opens the run. */
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
    <Table aria-label={label} className="text-[13px]">
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Status</TableHead>
          <TableHead>Workflow</TableHead>
          <TableHead>Repo</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Pull request</TableHead>
          <TableHead className="w-10">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id} data-run-id={run.id} className="relative">
            <TableCell>
              <div className="flex items-center gap-2">
                <StatusBadge status={badgeStatus(run.status)} />
                <ReviewLink run={run} />
              </div>
            </TableCell>
            <TableCell className="max-w-72 truncate">
              <Link href={`/runs/${run.id}`} className={STRETCHED}>
                {run.workflow.name}
              </Link>
              {run.rerun_of ? (
                <RerunOf runId={run.rerun_of} className="block text-xs text-muted-foreground" />
              ) : null}
            </TableCell>
            <TableCell>
              <Repo run={run} />
            </TableCell>
            <TableCell>
              <Started run={run} now={now} />
            </TableCell>
            <TableCell>
              <Duration run={run} now={now} />
            </TableCell>
            <TableCell>
              {run.pr_url ? (
                <PrLink url={run.pr_url} />
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="text-right">
              <RunMenu run={run} baseUrl={baseUrl} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** One run as a card, below `md`. The card opens the run. */
export function RunCard({ run, now, baseUrl }: { run: RunSummary; now: number; baseUrl?: string }) {
  return (
    <Card size="sm" data-run-id={run.id} className="relative px-3 hover:bg-muted/50">
      <div className="flex items-start justify-between gap-2">
        <Link href={`/runs/${run.id}`} className={cn(STRETCHED, "min-w-0 truncate")}>
          {run.workflow.name}
        </Link>
        <div className="flex shrink-0 items-center gap-1">
          <StatusBadge status={badgeStatus(run.status)} />
          <RunMenu run={run} baseUrl={baseUrl} />
        </div>
      </div>
      {run.rerun_of ? (
        <RerunOf runId={run.rerun_of} className="text-xs text-muted-foreground" />
      ) : null}
      <Repo run={run} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Started run={run} now={now} />
        <span>
          <span className="sr-only">Duration </span>
          <Duration run={run} now={now} />
        </span>
        {run.pr_url ? <PrLink url={run.pr_url} /> : null}
        <span className="ml-auto">
          <ReviewLink run={run} />
        </span>
      </div>
    </Card>
  );
}

/** Runs as a table from `md` and as cards below. */
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
      <ul aria-label={label} className="flex flex-col gap-2 md:hidden">
        {runs.map((run) => (
          <li key={run.id}>
            <RunCard run={run} now={now} baseUrl={baseUrl} />
          </li>
        ))}
      </ul>
    </>
  );
}
