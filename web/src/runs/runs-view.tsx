"use client";

import { FilterXIcon, HistoryIcon, LayoutTemplateIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId, useMemo, useState } from "react";

import { apiBaseUrl } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { NewRunSheet } from "./new-run/new-run-sheet";
import { filtersToQuery, isFiltered, NO_FILTERS, parseFilters, type RunFilters } from "./filters";
import { RunFiltersBar } from "./run-filters";
import { RunsList } from "./runs-list";
import { gateExpired, isLive, runStatusLabel } from "./summaries";
import { useNow } from "./use-now";
import { useRunList } from "./use-run-summaries";
import { useRunsStream } from "./use-runs-stream";

/**
 * The runs page (the home page): the runs that need approval first, then every run of the
 * workspace, newest first, kept live from `GET /runs/stream`. Filters live in the URL.
 */
export function RunsView({
  baseUrl = apiBaseUrl(),
  workspaceId = DEFAULT_WORKSPACE_ID,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = useMemo(
    () => parseFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const setFilters = (next: RunFilters) => {
    const query = filtersToQuery(next);
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  // A status filter already says which runs to show, so the "Needs approval" section is only
  // shown on top of an unfiltered (or template/repo filtered) list.
  const showWaiting = filters.status.length === 0;
  const all = useRunList(filters, { workspaceId, baseUrl });
  const waiting = useRunList(
    { ...filters, status: ["waiting"] },
    { workspaceId, baseUrl, limit: 100, enabled: showWaiting },
  );

  const [announcement, setAnnouncement] = useState("");
  const [newRun, setNewRun] = useState(false);
  const [newRunTemplate, setNewRunTemplate] = useState<string | null>(null);
  useRunsStream({
    workspaceId,
    baseUrl,
    onChange: (run, previous) => {
      if (previous && previous.status !== run.status) {
        setAnnouncement(`Run ${run.workflow.name} is now ${runStatusLabel(run)}.`);
      }
    },
  });

  const runs = all.data?.pages.flatMap((page) => page.items) ?? [];
  const waitingPages = showWaiting ? (waiting.data?.pages.flatMap((page) => page.items) ?? []) : [];
  const now = useNow(
    1000,
    [...runs, ...waitingPages].some((run) => isLive(run.status)),
  );
  // A gate past its time to live no longer needs approval, even before its run is cancelled.
  const waitingRuns = waitingPages.filter((run) => !gateExpired(run, now));
  const waitingHeading = useId();
  const allHeading = useId();

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        title="Runs"
        description="Every run in this workspace, newest first."
        actions={
          <Button type="button" onClick={() => setNewRun(true)}>
            <PlusIcon aria-hidden="true" data-icon="inline-start" />
            New run
          </Button>
        }
      />
      <NewRunSheet
        open={newRun}
        onOpenChange={setNewRun}
        templateId={newRunTemplate}
        onTemplateChange={setNewRunTemplate}
        workspaceId={workspaceId}
        baseUrl={baseUrl}
      />
      <RunFiltersBar
        filters={filters}
        onChange={setFilters}
        workspaceId={workspaceId}
        baseUrl={baseUrl}
      />
      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>

      {waitingRuns.length > 0 ? (
        <section aria-labelledby={waitingHeading} className="flex flex-col gap-3">
          <h2 id={waitingHeading} className="text-section font-semibold">
            Needs approval{" "}
            <span className="text-muted-foreground tabular-nums">({waitingRuns.length})</span>
          </h2>
          <RunsList
            runs={waitingRuns}
            now={now}
            label="Runs that need approval"
            baseUrl={baseUrl}
          />
        </section>
      ) : null}

      <section aria-labelledby={allHeading} className="flex flex-col gap-3">
        <h2 id={allHeading} className="text-section font-semibold">
          All runs
        </h2>
        {all.isPending ? (
          <LoadingState rows={5} label="Loading runs…" />
        ) : !all.data ? (
          <ErrorState
            message={all.error?.message ?? "Could not load runs."}
            onRetry={() => void all.refetch()}
          />
        ) : runs.length === 0 ? (
          isFiltered(filters) ? (
            <EmptyState
              icon={FilterXIcon}
              message="No runs match these filters."
              action={
                <Button type="button" variant="outline" onClick={() => setFilters(NO_FILTERS)}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={HistoryIcon}
              message="No runs yet. Start one from a template and it shows up here."
              action={
                <Button asChild>
                  <Link href="/templates">
                    <LayoutTemplateIcon aria-hidden="true" data-icon="inline-start" />
                    Browse templates
                  </Link>
                </Button>
              }
            />
          )
        ) : (
          <>
            <RunsList runs={runs} now={now} label="All runs" baseUrl={baseUrl} />
            {/* A failed later page keeps the runs already shown. */}
            {all.isFetchNextPageError ? (
              <ErrorState message={all.error.message} onRetry={() => void all.fetchNextPage()} />
            ) : null}
            {all.hasNextPage ? (
              <Button
                type="button"
                variant="outline"
                className="self-center"
                disabled={all.isFetchingNextPage}
                onClick={() => void all.fetchNextPage()}
              >
                {all.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
