"use client";

import { CopyIcon, ExternalLinkIcon, GitBranchIcon } from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { StatusBadge, type RunStatus } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import {
  costCaveat,
  formatCost,
  formatTokens,
  formatUsd,
  usageDetails,
  type TokenUsage,
} from "../cost";
import { RerunOf } from "../rerun";
import { formatAbsolute, formatDuration, formatRelative, repoLabel } from "../summaries";
import type { RunDetail } from "../use-run-detail";

export interface HeaderFacts {
  status: { status: RunStatus; label: string };
  workflowName: string | null;
  startedAt: string | null;
  durationMs: number | null;
  prUrl: string | null;
  usage: TokenUsage | null;
}

function Meta({ children }: { children: ReactNode }) {
  return <li className="flex min-w-0 items-center gap-1.5">{children}</li>;
}

/** The run console's header: what ran, where, when, how it is going, and what can be done. */
export function RunHeader({
  runId,
  run,
  facts,
  now,
  actions,
}: {
  runId: string;
  run: RunDetail | null | undefined;
  facts: HeaderFacts;
  now: number;
  actions?: ReactNode;
}) {
  const repo = run?.repo ?? null;
  const budget = run?.usage.budget_usd ?? null;
  return (
    <PageHeader
      title={facts.workflowName ?? run?.workflow.name ?? "Run"}
      description={
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px]">
          <Meta>
            <span aria-live="polite">
              <StatusBadge
                data-testid="run-status"
                status={facts.status.status}
                label={facts.status.label}
              />
            </span>
          </Meta>
          {repo ? (
            <Meta>
              <span className="truncate font-mono text-foreground">{repoLabel(repo.url)}</span>
              {repo.ref ? (
                <span className="flex min-w-0 items-center gap-1 font-mono">
                  <GitBranchIcon aria-hidden="true" className="size-3.5 shrink-0" />
                  <span className="truncate">{repo.ref}</span>
                </span>
              ) : null}
            </Meta>
          ) : null}
          {facts.startedAt ? (
            <Meta>
              <Tooltip>
                <TooltipTrigger asChild>
                  <time
                    dateTime={facts.startedAt}
                    tabIndex={0}
                    className="rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                  >
                    Started {formatRelative(facts.startedAt, now)}
                  </time>
                </TooltipTrigger>
                <TooltipContent>{formatAbsolute(facts.startedAt)}</TooltipContent>
              </Tooltip>
            </Meta>
          ) : null}
          {facts.durationMs !== null ? (
            <Meta>
              <span data-testid="run-duration" className="tabular-nums">
                {formatDuration(facts.durationMs)}
              </span>
            </Meta>
          ) : null}
          {facts.usage ? (
            <Meta>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span
                    data-testid="run-cost"
                    tabIndex={0}
                    className="rounded-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                  >
                    {formatCost(facts.usage)}
                    {budget !== null ? (
                      <span className="text-muted-foreground"> of {formatUsd(budget)}</span>
                    ) : null}
                    <span className="text-muted-foreground">
                      {" "}
                      · {formatTokens(facts.usage.inputTokens + facts.usage.outputTokens)} tokens
                    </span>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {usageDetails(facts.usage)}
                  {costCaveat(facts.usage) ? <p>{costCaveat(facts.usage)}</p> : null}
                  {budget !== null ? (
                    <p>The run stops once its cost reaches its {formatUsd(budget)} budget.</p>
                  ) : null}
                </TooltipContent>
              </Tooltip>
            </Meta>
          ) : budget !== null ? (
            <Meta>
              <span data-testid="run-cost" className="tabular-nums">
                Budget {formatUsd(budget)}
              </span>
            </Meta>
          ) : null}
          {run?.rerun_of ? (
            <Meta>
              <RerunOf runId={run.rerun_of} />
            </Meta>
          ) : null}
          {facts.prUrl ? (
            <Meta>
              <a
                data-testid="pull-request"
                href={facts.prUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline"
              >
                Pull request #{facts.prUrl.split("/").at(-1)}
                <ExternalLinkIcon aria-hidden="true" className="size-3.5 shrink-0" />
              </a>
            </Meta>
          ) : null}
        </ul>
      }
      actions={
        <>
          {actions}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void navigator.clipboard?.writeText(runId).then(
                () => toast.success("Run id copied"),
                () => toast.error("Could not copy the run id"),
              );
            }}
          >
            <CopyIcon aria-hidden="true" data-icon="inline-start" />
            <span className="sr-only">Copy run id</span>
            <span aria-hidden="true" className="font-mono">
              {runId.slice(0, 8)}
            </span>
          </Button>
        </>
      }
    />
  );
}
