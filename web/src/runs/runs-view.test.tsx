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

/** Answers `GET /runs` with `lists(query)`; GitHub is not connected. */
function api(lists: (query: URLSearchParams) => Response) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const url = new URL(request.url);
    if (url.pathname === "/runs") return lists(url.searchParams);
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

test("runs that need approval come first, then every run with its status", async () => {
  api((q) =>
    json(page(q.getAll("status").includes("waiting") ? [paused] : [paused, failed, done])),
  );
  show();

  const waiting = await screen.findByRole("table", { name: "Runs that need approval" });
  expect(within(waiting).getAllByRole("row")).toHaveLength(2);
  expect(within(waiting).getByText("Waiting")).toBeTruthy();
  expect(screen.getByRole("heading", { name: /Needs approval/ }).textContent).toContain("(1)");

  const all = screen.getByRole("table", { name: "All runs" });
  const rows = within(all).getAllByRole("row").slice(1);
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

test("with no waiting runs there is no Needs approval section", async () => {
  api((q) => json(page(q.getAll("status").length ? [] : [done])));
  show();

  await screen.findByRole("table", { name: "All runs" });
  expect(screen.queryByRole("heading", { name: /Needs approval/ })).toBeNull();
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
  nav.search = "status=failed&template=generate-docs";
  const fetch = api(() => json(page([])));
  show();

  expect(await screen.findByText("No runs match these filters.")).toBeTruthy();
  const runs = fetch.mock.calls.map(([r]) => new URL(r.url)).find((u) => u.pathname === "/runs");
  const query = runs!.searchParams;
  expect(query.getAll("status")).toEqual(["failed"]);
  expect(query.get("template")).toBe("generate-docs");
  // A status filter replaces the Needs approval section.
  expect(fetch.mock.calls.every(([r]) => !r.url.includes("status=waiting"))).toBe(true);

  fireEvent.click(screen.getAllByRole("button", { name: "Clear filters" })[0]!);
  expect(nav.replace).toHaveBeenCalledWith("/runs", { scroll: false });
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
  await waitFor(() => expect(within(all).getAllByRole("row")).toHaveLength(3));
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
