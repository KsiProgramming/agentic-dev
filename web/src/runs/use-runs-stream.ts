"use client";

import { useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiBaseUrl } from "@/api/client";

import { matchesFilters } from "./filters";
import type { RunSummary, RunSummaryPage } from "./summaries";
import { runsKey, type RunListKey } from "./use-run-summaries";

type Pages = InfiniteData<RunSummaryPage, string | null>;

function replace(data: Pages, run: RunSummary): Pages {
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => (item.id === run.id ? run : item)),
    })),
  };
}

/**
 * Bring every cached runs list of the workspace up to date with `run`'s new summary. A list
 * that shows the run gets it in place; a list it joins (a new run, or one that now matches its
 * filters) or leaves (a run that no longer matches, such as an approved one leaving "Needs
 * approval") is fetched again, so its order and pages stay the API's. Returns the summary the
 * cache had before, if any.
 */
export function applySummary(
  client: QueryClient,
  workspaceId: string,
  run: RunSummary,
): RunSummary | undefined {
  let previous: RunSummary | undefined;
  for (const query of client.getQueryCache().findAll({ queryKey: runsKey(workspaceId) })) {
    const key = query.queryKey as RunListKey;
    const data = query.state.data as Pages | undefined;
    if (!data) continue;
    const shown = data.pages.flatMap((page) => page.items).find((item) => item.id === run.id);
    const matches = matchesFilters(run, key[3]);
    if (shown) {
      previous ??= shown;
      if (matches) client.setQueryData<Pages>(key, (d) => (d ? replace(d, run) : d));
      else void client.invalidateQueries({ queryKey: key, exact: true });
    } else if (matches) {
      void client.invalidateQueries({ queryKey: key, exact: true });
    }
  }
  return previous;
}

/**
 * Keep the workspace's runs lists live from `GET /runs/stream`. The stream only sends changes
 * made after it connected, so after a reconnect the lists are fetched again. `onChange` hears
 * each summary with the one the lists showed before.
 */
export function useRunsStream({
  workspaceId,
  baseUrl = apiBaseUrl(),
  onChange,
}: {
  workspaceId: string;
  baseUrl?: string;
  onChange?: (run: RunSummary, previous: RunSummary | undefined) => void;
}) {
  const client = useQueryClient();
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  useEffect(() => {
    const source = new EventSource(
      `${baseUrl}/runs/stream?workspace_id=${encodeURIComponent(workspaceId)}`,
    );
    // The first connection follows the first fetch closely enough: the API also sends changes
    // made a few seconds before it. A reconnect may follow a long gap.
    let connected = false;
    source.addEventListener("open", () => {
      if (connected) void client.invalidateQueries({ queryKey: runsKey(workspaceId) });
      connected = true;
    });
    source.addEventListener("run_summary", (message: MessageEvent<string>) => {
      const run = JSON.parse(message.data) as RunSummary;
      const previous = applySummary(client, workspaceId, run);
      onChangeRef.current?.(run, previous);
    });
    return () => source.close();
  }, [client, baseUrl, workspaceId]);
}
