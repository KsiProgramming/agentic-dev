"use client";

import { ExternalLinkIcon, GitBranchIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Duration, IdChip, Money, RelativeTime, TokenCount } from "@/components/display";
import { PageHeader } from "@/components/page-header";
import { StatusBadge, type RunStatus } from "@/components/status-badge";

import type { TokenUsage } from "../cost";
import { RerunOf } from "../rerun";
import { repoLabel } from "../summaries";
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
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-meta">
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
              <RelativeTime iso={facts.startedAt} now={now} prefix="Started " />
            </Meta>
          ) : null}
          {facts.durationMs !== null ? (
            <Meta>
              <Duration data-testid="run-duration" ms={facts.durationMs} />
            </Meta>
          ) : null}
          {facts.usage ? (
            <Meta>
              <Money data-testid="run-cost" usage={facts.usage} budget={budget} />
              <span className="text-muted-foreground">
                ·{" "}
                <TokenCount
                  value={facts.usage.inputTokens + facts.usage.outputTokens}
                  label="tokens"
                  usage={facts.usage}
                />
              </span>
            </Meta>
          ) : budget !== null ? (
            <Meta>
              <span data-testid="run-cost">
                Budget <Money usd={budget} />
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
          <IdChip id={runId} label="run id" className="h-8" />
        </>
      }
    />
  );
}
