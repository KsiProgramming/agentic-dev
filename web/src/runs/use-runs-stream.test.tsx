import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { NO_FILTERS, type RunFilters } from "./filters";
import type { RunSummary, RunSummaryPage } from "./summaries";
import { FakeEventSource, runSummary } from "./testing";
import { runListKey } from "./use-run-summaries";
import { applySummary, useRunsStream } from "./use-runs-stream";

const WS = "00000000-0000-0000-0000-000000000001";
const WAITING: RunFilters = { ...NO_FILTERS, status: ["waiting"] };

const done = runSummary({ id: "r1" });
const paused = runSummary({
  id: "r2",
  status: "waiting",
  finished_at: null,
  duration_ms: null,
  waiting_gate: { node_id: "gate", title: "Approve" },
});

function seed(client: QueryClient, filters: RunFilters, items: RunSummary[]) {
  const data: InfiniteData<RunSummaryPage, string | null> = {
    pages: [{ items, next_cursor: null }],
    pageParams: [null],
  };
  client.setQueryData(runListKey(WS, filters, 25), data);
}

function items(client: QueryClient, filters: RunFilters) {
  const data = client.getQueryData<InfiniteData<RunSummaryPage>>(runListKey(WS, filters, 25));
  return data?.pages.flatMap((page) => page.items);
}

function invalidated(client: QueryClient, filters: RunFilters) {
  return client.getQueryState(runListKey(WS, filters, 25))?.isInvalidated;
}

let client: QueryClient;

beforeEach(() => {
  client = new QueryClient();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a shown run is updated in place and its previous summary returned", () => {
  seed(client, NO_FILTERS, [paused, done]);
  const running = { ...paused, status: "running" as const, waiting_gate: null };

  const previous = applySummary(client, WS, running);

  expect(previous).toEqual(paused);
  expect(items(client, NO_FILTERS)).toEqual([running, done]);
  expect(invalidated(client, NO_FILTERS)).toBe(false);
});

test("a run that leaves a list's filters refetches that list", () => {
  seed(client, NO_FILTERS, [paused]);
  seed(client, WAITING, [paused]);

  applySummary(client, WS, { ...paused, status: "running", waiting_gate: null });

  expect(invalidated(client, WAITING)).toBe(true);
  expect(invalidated(client, NO_FILTERS)).toBe(false);
});

test("a new run refetches the lists it belongs to only", () => {
  seed(client, NO_FILTERS, [done]);
  seed(client, WAITING, []);
  const fresh = runSummary({ id: "r3", status: "queued", started_at: null, finished_at: null });

  expect(applySummary(client, WS, fresh)).toBeUndefined();

  expect(invalidated(client, NO_FILTERS)).toBe(true);
  expect(invalidated(client, WAITING)).toBe(false);
});

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

test("the hook streams the workspace's summaries into the cache", () => {
  seed(client, NO_FILTERS, [paused]);
  const onChange = vi.fn();
  const { unmount } = renderHook(
    () => useRunsStream({ workspaceId: WS, baseUrl: "http://api.test", onChange }),
    { wrapper },
  );
  const source = FakeEventSource.latest();
  expect(source.url).toBe(`http://api.test/runs/stream?workspace_id=${WS}`);

  const completed = { ...paused, status: "completed" as const, waiting_gate: null };
  act(() => source.send("run_summary", completed));

  expect(items(client, NO_FILTERS)).toEqual([completed]);
  expect(onChange).toHaveBeenCalledWith(completed, paused);

  unmount();
  expect(source.readyState).toBe(FakeEventSource.CLOSED);
});

test("a reconnect refetches the lists; the first connection does not", () => {
  seed(client, NO_FILTERS, [done]);
  renderHook(() => useRunsStream({ workspaceId: WS, baseUrl: "http://api.test" }), { wrapper });
  const source = FakeEventSource.latest();

  act(() => source.open());
  expect(invalidated(client, NO_FILTERS)).toBe(false);

  act(() => source.open());
  expect(invalidated(client, NO_FILTERS)).toBe(true);
});
