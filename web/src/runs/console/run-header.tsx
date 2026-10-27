"use client";

import {
  DownloadIcon,
  EllipsisIcon,
  GitBranchIcon,
  GitPullRequestIcon,
  LinkIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { IdChip, RelativeTime, shortId } from "@/components/display";
import { PageHeader } from "@/components/page-header";
import { StatusBadge, type RunStatus } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import type { TokenUsage } from "../cost";
import { RerunOf } from "../rerun";
import { repoLabel } from "../summaries";
import type { ReceivedRunEvent } from "../types";
import type { RunDetail } from "../use-run-detail";
import { pullRequestNumber } from "./run-stats";

export interface HeaderFacts {
  status: { status: RunStatus; label: string };
  workflowName: string | null;
  startedAt: string | null;
  /** The run's duration: the time it worked. */
  activeMs: number | null;
  /** The time it was paused at gates, growing while `waitingLive`. */
  waitingMs: number;
  waitingLive: boolean;
  /** Start to end, for the start time's tooltip only. */
  wallClock: string | undefined;
  prUrl: string | null;
  usage: TokenUsage | null;
}

/** What started the run: "Manual", "API" or "Rerun of <id>". */
function Trigger({ run }: { run: RunDetail }) {
  if (run.rerun_of) return <RerunOf runId={run.rerun_of} />;
  return (
    <span>{run.trigger === "manual" ? "Manual" : run.trigger === "api" ? "API" : "Rerun"}</span>
  );
}

/** Saves the events the console received as `run-<id8>-events.json`, built in the browser. */
function downloadEvents(runId: string, events: ReceivedRunEvent[]) {
  // As the API logged them: without when this browser received them.
  const plain = events.map((event) => {
    const copy: Partial<ReceivedRunEvent> = { ...event };
    delete copy.receivedAt;
    return copy;
  });
  const blob = new Blob([JSON.stringify(plain, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `run-${shortId(runId)}-events.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function copyLink() {
  void navigator.clipboard
    ?.writeText(window.location.href)
    .then(() => toast.success("Link copied"))
    .catch(() => toast.error("Could not copy the link"));
}

/** The run's other actions, in a "⋯" menu: Copy link, Download events. */
function RunMenu({ runId, events }: { runId: string; events: ReceivedRunEvent[] }) {
  // Not modal: a modal menu hides the rest of the page with `aria-hidden` while its links and
  // buttons stay focusable (axe: aria-hidden-focus).
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="icon-sm" aria-label="More actions">
          <EllipsisIcon aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={copyLink}>
          <LinkIcon aria-hidden="true" />
          Copy link
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={events.length === 0}
          onSelect={() => downloadEvents(runId, events)}
        >
          <DownloadIcon aria-hidden="true" />
          Download events
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * The run console's header: what ran, its status and id; where (repo › branch), who started it
 * and when; then the pull request as the primary action once opened, Rerun or Cancel, and "⋯".
 */
export function RunHeader({
  runId,
  run,
  facts,
  now,
  events,
  actions,
}: {
  runId: string;
  run: RunDetail | null | undefined;
  facts: HeaderFacts;
  now: number;
  events: ReceivedRunEvent[];
  actions?: ReactNode;
}) {
  const repo = run?.repo ?? null;
  const branch = run?.branch ?? repo?.ref ?? null;
  return (
    <PageHeader
      title={facts.workflowName ?? run?.workflow.name ?? "Run"}
      aside={
        <>
          <span aria-live="polite">
            <StatusBadge
              data-testid="run-status"
              status={facts.status.status}
              label={facts.status.label}
            />
          </span>
          <IdChip id={runId} label="run id" />
        </>
      }
      description={
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-meta">
          {repo ? (
            <li className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-mono text-foreground">{repoLabel(repo.url)}</span>
              {branch ? (
                <span className="flex min-w-0 items-center gap-1 font-mono">
                  <span aria-hidden="true">›</span>
                  <GitBranchIcon aria-hidden="true" className="size-3.5 shrink-0" />
                  <span className="truncate">{branch}</span>
                </span>
              ) : null}
            </li>
          ) : null}
          {run ? (
            <li className="flex min-w-0 items-center gap-1.5">
              <Trigger run={run} />
            </li>
          ) : null}
          {facts.startedAt ? (
            <li className="flex min-w-0 items-center gap-1.5">
              <RelativeTime
                iso={facts.startedAt}
                now={now}
                prefix="Started "
                detail={facts.wallClock}
              />
            </li>
          ) : null}
        </ul>
      }
      actions={
        <>
          {facts.prUrl ? (
            <Button asChild size="sm">
              <a data-testid="pull-request" href={facts.prUrl} target="_blank" rel="noreferrer">
                <GitPullRequestIcon aria-hidden="true" data-icon="inline-start" />
                Pull request {pullRequestNumber(facts.prUrl)}
              </a>
            </Button>
          ) : null}
          {actions}
          <RunMenu runId={runId} events={events} />
        </>
      }
    />
  );
}
