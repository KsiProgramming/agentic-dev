"use client";

import {
  ActivityIcon,
  CircleCheckIcon,
  FilterXIcon,
  HistoryIcon,
  InboxIcon,
  LayoutTemplateIcon,
  PlusIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { apiBaseUrl } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useWorkspaceId } from "@/workspace";

import { NewRunSheet } from "./new-run/new-run-sheet";
import {
  isFiltered,
  parseRunsQuery,
  RUN_VIEWS,
  runsQueryToString,
  viewFilters,
  type RunsQuery,
  type RunViewId,
} from "./filters";
import { RunFiltersBar } from "./run-filters";
import { RunViewTabs } from "./run-views";
import { RunsList } from "./runs-list";
import { gateExpired, isLive, runStatusLabel } from "./summaries";
import { useNow } from "./use-now";
import { useRunCounts } from "./use-run-counts";
import { useRunList } from "./use-run-summaries";
import { useRunsStream } from "./use-runs-stream";

/** What an empty view says, beyond All with no runs at all. */
const EMPTY_VIEW: Record<Exclude<RunViewId, "all">, { icon: LucideIcon; message: string }> = {
  running: { icon: ActivityIcon, message: "No run is running right now." },
  waiting: { icon: InboxIcon, message: "Nothing needs approval." },
  failed: { icon: CircleCheckIcon, message: "No run has failed." },
};

/**
 * The runs page (the home page): saved views as tabs with their counts (All, Running, Needs
 * approval, Failed), then the view's runs, newest first under date headers, kept live from
 * `GET /runs/stream`. Nothing is pinned above the list. The view and filters live in the URL.
 */
export function RunsView({
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
  const query = useMemo(
    () => parseRunsQuery(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const setQuery = (next: RunsQuery) => {
    const search = runsQueryToString(next);
    router.replace(search ? `${pathname}?${search}` : pathname, { scroll: false });
  };

  const list = useRunList(viewFilters(query), { workspaceId, baseUrl });
  const counts = useRunCounts(query, { workspaceId, baseUrl });

  const [announcement, setAnnouncement] = useState("");
  const [newRun, setNewRun] = useState(false);
  // `?new=1` (the command palette's "New run") opens the sheet; closing it drops the param.
  const askedNewRun = searchParams.get("new") === "1";
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

  const loaded = list.data?.pages.flatMap((page) => page.items) ?? [];
  const now = useNow(
    1000,
    loaded.some((run) => isLive(run.status)),
  );
  // A gate past its time to live no longer needs approval, even before its run is cancelled.
  const runs = query.view === "waiting" ? loaded.filter((run) => !gateExpired(run, now)) : loaded;
  const viewLabel = RUN_VIEWS.find((v) => v.id === query.view)?.label ?? "All";

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
        tabs={<RunViewTabs query={query} counts={counts.data} pathname={pathname} />}
      />
      <NewRunSheet
        open={newRun || askedNewRun}
        onOpenChange={(open) => {
          setNewRun(open);
          if (!open && askedNewRun) setQuery(query);
        }}
        templateId={newRunTemplate}
        onTemplateChange={setNewRunTemplate}
        workspaceId={workspaceId}
        baseUrl={baseUrl}
      />
      <div className="flex flex-col gap-3">
        <RunFiltersBar
          filters={query}
          onChange={setQuery}
          workspaceId={workspaceId}
          baseUrl={baseUrl}
        />
      </div>
      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>

      <section aria-label={`${viewLabel} runs`} className="flex flex-col gap-3">
        {list.isPending ? (
          <LoadingState rows={5} label="Loading runs…" />
        ) : !list.data ? (
          <ErrorState
            message={list.error?.message ?? "Could not load runs."}
            onRetry={() => void list.refetch()}
          />
        ) : runs.length === 0 ? (
          <EmptyView
            query={query}
            onClear={() => setQuery({ ...query, template: null, repo: null })}
          />
        ) : (
          <>
            <RunsList runs={runs} now={now} label={`${viewLabel} runs`} baseUrl={baseUrl} />
            {/* A failed later page keeps the runs already shown. */}
            {list.isFetchNextPageError ? (
              <ErrorState message={list.error.message} onRetry={() => void list.fetchNextPage()} />
            ) : null}
            {list.hasNextPage ? (
              <Button
                type="button"
                variant="outline"
                className="self-center"
                disabled={list.isFetchingNextPage}
                onClick={() => void list.fetchNextPage()}
              >
                {list.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}

/** The empty state of a view: filters to clear, a view with nothing in it, or no runs at all. */
function EmptyView({ query, onClear }: { query: RunsQuery; onClear: () => void }) {
  if (isFiltered(query)) {
    return (
      <EmptyState
        icon={FilterXIcon}
        message="No runs match these filters."
        action={
          <Button type="button" onClick={onClear}>
            Clear filters
          </Button>
        }
      />
    );
  }
  if (query.view !== "all") {
    const { icon, message } = EMPTY_VIEW[query.view];
    return (
      <EmptyState
        icon={icon}
        message={message}
        action={
          <Button asChild>
            <Link href="/runs" scroll={false}>
              Show all runs
            </Link>
          </Button>
        }
      />
    );
  }
  return (
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
  );
}
