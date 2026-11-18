"use client";

import { NO_FILTERS, type RunFilters } from "@/runs/filters";
import { gateExpired, type RunSummary } from "@/runs/summaries";
import { useRunList } from "@/runs/use-run-summaries";

/** Waiting runs listed at most; more shows as "99+" in the count. */
export const WAITING_LIMIT = 100;

const WAITING: RunFilters = { ...NO_FILTERS, status: ["waiting"] };

/** The workspace's runs waiting at a gate, as one list the shell's count and the Inbox share
 * (one query key), kept live by the shell's runs stream. */
export function useWaitingRuns({ workspaceId, baseUrl }: { workspaceId: string; baseUrl: string }) {
  return useRunList(WAITING, { workspaceId, baseUrl, limit: WAITING_LIMIT });
}

/** The gates an approver works through, oldest run first: a gate past its time to live is left
 * out, even before the worker has cancelled its run. */
export function inboxRuns(runs: readonly RunSummary[], now: number): RunSummary[] {
  return (
    runs
      // A run waiting for an answer on Jira (7.9) has nothing for an approver to decide.
      .filter(
        (run) => run.status === "waiting" && !run.waiting_gate?.wait_for && !gateExpired(run, now),
      )
      .sort(
        (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id.localeCompare(b.id),
      )
  );
}
