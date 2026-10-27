import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { RunsView } from "./runs-view";
import type { RunSummary, RunSummaryPage } from "./summaries";
import { FakeEventSource, runSummary } from "./testing";

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/runs",
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

const done = runSummary({ id: "r1", pr_url: "https://github.com/acme/docs/pull/12" });
const failed = runSummary({ id: "r2", status: "failed", workflow: { id: "w", name: "Audit" } });
const paused = runSummary({
  id: "r3",
  status: "waiting",
  workflow: { id: "w", name: "Docs with gate" },
  finished_at: null,
  duration_ms: null,
  waiting_gate: { node_id: "gate", title: "Approve" },
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function page(items: RunSummary[], next_cursor: string | null = null): RunSummaryPage {
  return { items, next_cursor };
}

const COUNTS = { all: 3, running: 0, waiting: 1, failed: 1 };

/** Answers `GET /runs` with `lists(query)` and `GET /runs/counts` with `COUNTS`; GitHub is not
 * connected. */
function api(lists: (query: URLSearchParams) => Response) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const url = new URL(request.url);
    if (url.pathname === "/runs") return lists(url.searchParams);
    if (url.pathname === "/runs/counts") return json(COUNTS);
    if (url.pathname.endsWith("/repos")) return json({ detail: "not connected" }, 409);
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RunsView baseUrl="http://api.test" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  nav.search = "";
  nav.replace.mockReset();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("Done when (11.4): every run is listed newest first, nothing is pinned above", async () => {
  api((q) => json(page(q.getAll("status").length ? [] : [paused, failed, done])));
  show();

  const all = await screen.findByRole("table", { name: "All runs" });
  // Only one list: the waiting run is a row like the others.
  expect(screen.getAllByRole("table")).toHaveLength(1);
  const rows = within(all)
    .getAllByRole("row")
    .filter((row) => row.dataset.runId);
  expect(
    rows.map((row) => within(row).getAllByText(/^(Waiting|Failed|Succeeded)$/)[0]?.textContent),
  ).toEqual(["Waiting", "Failed", "Succeeded"]);
  expect(within(rows[2]!).getByText("2m 05s")).toBeTruthy();
  expect(within(rows[2]!).getByText("acme/docs")).toBeTruthy();
  const pr = within(rows[2]!).getByRole("link", { name: "Pull request #12 (opens in a new tab)" });
  expect(pr.getAttribute("href")).toBe("https://github.com/acme/docs/pull/12");
  expect(within(rows[1]!).getByRole("link", { name: "Audit" }).getAttribute("href")).toBe(
    "/runs/r2",
  );
});

test("the views are tabs with their counts; the current one is marked", async () => {
  api(() => json(page([done])));
  show();
  await screen.findByRole("table", { name: "All runs" });

  const views = within(screen.getByRole("navigation", { name: "Views" }));
  await waitFor(() => expect(screen.getByTestId("view-count-waiting").textContent).toBe(", 1"));
  const tabs = views.getAllByRole("link");
  expect(tabs.map((t) => t.textContent)).toEqual([
    "All, 3",
    "Running, 0",
    "Needs approval, 1",
    "Failed, 1",
  ]);
  expect(tabs[0]!.getAttribute("aria-current")).toBe("page");
  // A waiting run is one click away.
  expect(views.getByRole("link", { name: /^Needs approval/ }).getAttribute("href")).toBe(
    "/runs?view=waiting",
  );
});

test("a view comes from the URL and asks the API for its statuses", async () => {
  nav.search = "view=running";
  const fetch = api(() => json(page([])));
  show();

  expect(await screen.findByText("No run is running right now.")).toBeTruthy();
  const runs = fetch.mock.calls.map(([r]) => new URL(r.url)).find((u) => u.pathname === "/runs");
  expect(runs!.searchParams.getAll("status")).toEqual(["running", "queued"]);
  const views = within(screen.getByRole("navigation", { name: "Views" }));
  expect(views.getByRole("link", { name: /^Running/ }).getAttribute("aria-current")).toBe("page");
  expect(screen.getByRole("link", { name: "Show all runs" }).getAttribute("href")).toBe("/runs");
});

test("Needs approval leaves out a gate past its time to live", async () => {
  nav.search = "view=waiting";
  const stale = {
    ...paused,
    id: "r4",
    waiting_gate: { node_id: "gate", title: "Old", expires_at: "2020-01-01T00:00:00Z" },
  };
  api(() => json(page([stale])));
  show();

  expect(await screen.findByText("Nothing needs approval.")).toBeTruthy();
});

test("no runs at all points at the templates", async () => {
  api(() => json(page([])));
  show();

  expect(await screen.findByText(/No runs yet/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Browse templates" }).getAttribute("href")).toBe(
    "/templates",
  );
});

test("filters come from the URL and are sent to the API", async () => {
  nav.search = "view=failed&template=generate-docs";
  const fetch = api(() => json(page([])));
  show();

  expect(await screen.findByText("No runs match these filters.")).toBeTruthy();
  const urls = fetch.mock.calls.map(([r]) => new URL(r.url));
  const runs = urls.find((u) => u.pathname === "/runs")!.searchParams;
  expect(runs.getAll("status")).toEqual(["failed"]);
  expect(runs.get("template")).toBe("generate-docs");
  // The counts are for the same filters.
  const counts = urls.find((u) => u.pathname === "/runs/counts")!.searchParams;
  expect(counts.get("template")).toBe("generate-docs");

  // Clearing the filters keeps the view.
  fireEvent.click(screen.getAllByRole("button", { name: "Clear filters" })[0]!);
  expect(nav.replace).toHaveBeenCalledWith("/runs?view=failed", { scroll: false });
});

test("choosing a template puts it in the URL", async () => {
  api(() => json(page([done])));
  show();
  await screen.findByRole("table", { name: "All runs" });

  fireEvent.change(screen.getByLabelText("Template"), { target: { value: "generate-docs" } });

  expect(nav.replace).toHaveBeenCalledWith("/runs?template=generate-docs", { scroll: false });
});

test("a failed load can be retried", async () => {
  let fail = true;
  api((q) =>
    q.getAll("status").length ? json(page([])) : fail ? json({}, 500) : json(page([done])),
  );
  show();

  expect((await screen.findByRole("alert")).textContent).toContain("HTTP 500");
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect(await screen.findByRole("table", { name: "All runs" })).toBeTruthy();
});

test("Load more appends the next page", async () => {
  const fetch = api((q) => {
    if (q.getAll("status").length) return json(page([]));
    return q.get("cursor") === "c1" ? json(page([failed])) : json(page([done], "c1"));
  });
  show();
  await screen.findByRole("table", { name: "All runs" });

  fireEvent.click(screen.getByRole("button", { name: "Load more" }));

  const all = screen.getByRole("table", { name: "All runs" });
  await waitFor(() =>
    expect(
      within(all)
        .getAllByRole("row")
        .filter((row) => row.dataset.runId),
    ).toHaveLength(2),
  );
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  expect(fetch.mock.calls.some(([r]) => r.url.includes("cursor=c1"))).toBe(true);
});

test("a streamed change updates the row and is announced", async () => {
  api((q) => json(page(q.getAll("status").length ? [] : [failed, done])));
  show();
  const all = await screen.findByRole("table", { name: "All runs" });

  act(() => FakeEventSource.latest().send("run_summary", { ...done, status: "cancelled" }));

  await waitFor(() => expect(within(all).getByText("Cancelled")).toBeTruthy());
  expect(screen.getByText("Run Generate docs is now Cancelled.")).toBeTruthy();
});

test("?new=1 (the command palette's New run) opens the sheet; closing it drops the param", async () => {
  nav.search = "new=1";
  api(() => json(page([done])));
  show();

  const sheet = await screen.findByRole("dialog", { name: "New run" });
  fireEvent.keyDown(sheet, { key: "Escape" });

  await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/runs", { scroll: false }));
});
