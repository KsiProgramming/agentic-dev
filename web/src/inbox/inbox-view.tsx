"use client";

import { HistoryIcon, InboxIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { apiBaseUrl } from "@/api/client";
import { ExpiresIn, WaitingTime } from "@/components/display";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { LG_UP, useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";
import { repoLabel, runTimes, type RunSummary } from "@/runs/summaries";
import { useNow } from "@/runs/use-now";
import { useWorkspaceId } from "@/workspace";

import { InboxReview, NoLongerWaiting } from "./inbox-review";
import { inboxRuns, useWaitingRuns } from "./waiting";

/**
 * The Inbox (tech-stack → Inbox): the gates waiting in the workspace, oldest first, and the
 * selected one's review beside the list from 1024 px (below it under that). The selection lives
 * in the URL (`?run=`); from 1024 px the first gate is selected when none is. After a decision
 * the next gate is selected. The list is the shell's waiting count's, kept live by its stream.
 */
export function InboxView({
  baseUrl = apiBaseUrl(),
  workspaceId: givenWorkspaceId,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const workspaceId = useWorkspaceId(givenWorkspaceId);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const wide = useMediaQuery(LG_UP);
  const list = useWaitingRuns({ workspaceId, baseUrl });
  const loaded = list.data?.pages[0]?.items ?? [];
  const now = useNow(1000, loaded.length > 0);
  // Gates decided here: out of the list at once, before the stream reports the run moved on.
  const [decided, setDecided] = useState<ReadonlySet<string>>(new Set());
  const runs = inboxRuns(loaded, now).filter((run) => !decided.has(gateKey(run)));

  const requested = searchParams.get("run");
  const selectedId = requested ?? (wide ? (runs[0]?.id ?? null) : null);
  const selected = runs.find((run) => run.id === selectedId);
  const select = (id: string | null) =>
    router.replace(id ? `${pathname}?run=${encodeURIComponent(id)}` : pathname, { scroll: false });

  const onDecided = (run: RunSummary) => {
    const index = runs.findIndex((r) => r.id === run.id);
    const rest = runs.filter((r) => r.id !== run.id);
    setDecided((current) => new Set(current).add(gateKey(run)));
    select((rest[index] ?? rest[index - 1])?.id ?? null);
  };

  // Under 1024 px the review sits below the list: bring it into view when a gate is chosen.
  const review = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!wide && requested) review.current?.scrollIntoView({ block: "start" });
  }, [wide, requested]);

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader title="Inbox" description="Gates waiting for a decision, oldest first." />
      {list.isPending ? (
        <LoadingState rows={4} label="Loading the Inbox…" />
      ) : !list.data ? (
        <ErrorState
          message={list.error?.message ?? "Could not load the Inbox."}
          onRetry={() => void list.refetch()}
        />
      ) : runs.length === 0 && !requested ? (
        <EmptyState
          icon={InboxIcon}
          message="Nothing waits for your approval."
          action={
            <Button asChild variant="outline">
              <Link href="/runs">
                <HistoryIcon aria-hidden="true" data-icon="inline-start" />
                Show all runs
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)] lg:items-start">
          {runs.length > 0 ? (
            <InboxList runs={runs} selectedId={selectedId} now={now} pathname={pathname} />
          ) : (
            <EmptyState icon={InboxIcon} message="Nothing else waits for your approval." />
          )}
          {selectedId ? (
            <div ref={review} className="min-w-0 scroll-mt-20">
              {selected ? (
                <InboxReview
                  run={selected}
                  now={now}
                  baseUrl={baseUrl}
                  shortcuts
                  onDecided={() => onDecided(selected)}
                />
              ) : (
                <NoLongerWaiting runId={selectedId} />
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** A run's gate: a run that waits again later, at another gate, is a new entry. */
function gateKey(run: RunSummary): string {
  return `${run.id}:${run.waiting_gate?.node_id ?? ""}`;
}

/** The waiting gates: each a link that selects it, the selected one marked current. */
function InboxList({
  runs,
  selectedId,
  now,
  pathname,
}: {
  runs: RunSummary[];
  selectedId: string | null;
  now: number;
  pathname: string;
}) {
  return (
    <nav aria-label="Waiting gates" className="min-w-0">
      <ul className="flex flex-col divide-y rounded-lg border bg-card">
        {runs.map((run) => {
          const current = run.id === selectedId;
          const expiresAt = run.waiting_gate?.expires_at;
          return (
            <li key={run.id}>
              <Link
                href={`${pathname}?run=${encodeURIComponent(run.id)}`}
                scroll={false}
                aria-current={current ? "true" : undefined}
                className={cn(
                  "flex flex-col gap-1 px-4 py-3 outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
                  current && "bg-muted",
                )}
              >
                <span className="truncate font-medium">
                  {run.waiting_gate?.title ?? "Approve?"}
                </span>
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 text-meta text-muted-foreground">
                  <span className="truncate">{run.workflow.name}</span>
                  {run.repo ? (
                    <span title={run.repo.url} className="truncate font-mono">
                      {repoLabel(run.repo.url)}
                    </span>
                  ) : null}
                </span>
                <span className="flex flex-wrap items-center gap-x-2 text-meta text-muted-foreground">
                  <WaitingTime ms={runTimes(run, now).waitingMs} live />
                  {expiresAt ? (
                    <>
                      <span aria-hidden="true">·</span>
                      <ExpiresIn iso={expiresAt} now={now} focusable={false} />
                    </>
                  ) : null}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
