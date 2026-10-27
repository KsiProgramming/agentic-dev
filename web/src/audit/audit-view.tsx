"use client";

import { FilterXIcon, RefreshCwIcon, ScrollTextIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { apiBaseUrl } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { useNow } from "@/runs/use-now";
import { useWorkspaceId } from "@/workspace";

import { AuditFiltersBar } from "./audit-filters";
import { AuditList } from "./audit-list";
import {
  auditFiltersToQuery,
  isAuditFiltered,
  NO_AUDIT_FILTERS,
  parseAuditFilters,
  type AuditFilters,
} from "./filters";
import { useAuditLog } from "./use-audit-log";

/**
 * The audit log page (roadmap 3.7): every run, gate decision and settings change of the
 * workspace, newest first. It does not update live; Refresh reloads it. Filters live in the URL.
 */
export function AuditView({
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
  const filters = useMemo(
    () => parseAuditFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const setFilters = (next: AuditFilters) => {
    const query = auditFiltersToQuery(next);
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const log = useAuditLog(filters, { workspaceId, baseUrl });
  const events = log.data?.pages.flatMap((page) => page.items) ?? [];
  const now = useNow(60_000, events.length > 0);
  const refreshing = log.isRefetching && !log.isFetchingNextPage;

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        title="Audit log"
        description="Every run, approval and settings change in this workspace, newest first."
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={refreshing}
            onClick={() => void log.refetch()}
          >
            <RefreshCwIcon
              aria-hidden="true"
              data-icon="inline-start"
              className={refreshing ? "motion-safe:animate-spin" : undefined}
            />
            Refresh
          </Button>
        }
      />
      <AuditFiltersBar filters={filters} onChange={setFilters} />

      {log.isPending ? (
        <LoadingState rows={6} label="Loading the audit log…" />
      ) : !log.data ? (
        <ErrorState
          message={log.error?.message ?? "Could not load the audit log."}
          onRetry={() => void log.refetch()}
        />
      ) : events.length === 0 ? (
        isAuditFiltered(filters) ? (
          <EmptyState
            icon={FilterXIcon}
            message="No activity matches these filters."
            action={
              <Button type="button" variant="outline" onClick={() => setFilters(NO_AUDIT_FILTERS)}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={ScrollTextIcon}
            message="No activity yet. Runs, approvals and settings changes show up here."
          />
        )
      ) : (
        <>
          <AuditList events={events} now={now} />
          {/* A failed later page keeps the entries already shown. */}
          {log.isFetchNextPageError ? (
            <ErrorState message={log.error.message} onRetry={() => void log.fetchNextPage()} />
          ) : null}
          {log.hasNextPage ? (
            <Button
              type="button"
              variant="outline"
              className="self-center"
              disabled={log.isFetchingNextPage}
              onClick={() => void log.fetchNextPage()}
            >
              {log.isFetchingNextPage ? "Loading…" : "Load more"}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
