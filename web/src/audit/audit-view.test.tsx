import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { AuditEvent, AuditPage } from "./actions";
import { AuditView } from "./audit-view";
import { auditEvent } from "./testing";

const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/audit",
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

const RUN = "1a2b3c4d-0000-4000-8000-000000000001";
const created = auditEvent({ id: 1 });
const approved = auditEvent({
  id: 2,
  action: "gate.approved",
  node_id: "approve",
  details: { comment: "ok", edited_files: 1, edited_paths: ["a.md"] },
});
const ended = auditEvent({
  id: 3,
  action: "run.ended",
  actor: { type: "system", id: null },
  details: { status: "completed", estimated_usd: "0.5" },
});
const key = auditEvent({
  id: 4,
  action: "connection.added",
  run_id: null,
  run: null,
  details: { provider: "claude", key_hint: "1234", replaced: false },
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function page(items: AuditEvent[], next_cursor: string | null = null): AuditPage {
  return { items, next_cursor };
}

/** Answers `GET /workspaces/{id}/audit` with `answer(query)`. */
function api(answer: (query: URLSearchParams) => Response) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith("/audit")) return answer(url.searchParams);
    throw new Error(`unexpected ${request.method} ${request.url}`);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuditView baseUrl="http://api.test" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  nav.search = "";
  nav.replace.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("each entry shows its action, actor, run and what it did", async () => {
  api(() => json(page([key, ended, approved, created])));
  show();

  const table = await screen.findByRole("table", { name: "Audit log" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows.map((r) => r.getAttribute("data-action"))).toEqual([
    "connection.added",
    "run.ended",
    "gate.approved",
    "run.created",
  ]);
  expect(within(rows[0]!).getByText("Added Claude key ····1234")).toBeTruthy();
  expect(within(rows[1]!).getByText("System")).toBeTruthy();
  expect(within(rows[2]!).getByText("Approved approve with edits to 1 file · “ok”")).toBeTruthy();
  expect(within(rows[2]!).getByText(/recorded once sign-in exists/)).toBeTruthy();
  const run = within(rows[3]!).getByRole("link", { name: "Run 1a2b3c4d" });
  expect(run.getAttribute("href")).toBe(`/runs/${RUN}`);
  expect(within(rows[3]!).getByText("generate-docs · acme/docs")).toBeTruthy();
  // The cards for narrow screens hold the same entries.
  const cards = screen.getByRole("list", { name: "Audit log" });
  expect(within(cards).getAllByRole("listitem")).toHaveLength(4);
});

test("an empty log and a filtered empty log each have their state", async () => {
  api(() => json(page([])));
  const { unmount } = show();
  expect(await screen.findByText(/No activity yet/)).toBeTruthy();
  unmount();

  nav.search = "category=settings";
  show();
  expect(await screen.findByText("No activity matches these filters.")).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: "Clear filters" })[0]!);
  expect(nav.replace).toHaveBeenCalledWith("/audit", { scroll: false });
});

test("a failed load offers Retry", async () => {
  let fail = true;
  api(() => (fail ? json({ detail: "boom" }, 500) : json(page([created]))));
  show();

  expect(await screen.findByText(/Could not load the audit log \(HTTP 500\)/)).toBeTruthy();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
  expect(await screen.findByRole("table", { name: "Audit log" })).toBeTruthy();
});

test("filters from the URL narrow the query, and Load more fetches the next page", async () => {
  nav.search = `category=approvals&run=${RUN}`;
  const fetch = api((q) =>
    q.get("cursor") === "c2" ? json(page([created])) : json(page([approved], "c2")),
  );
  show();

  await screen.findByRole("table", { name: "Audit log" });
  const first = new URL(fetch.mock.calls[0]![0].url).searchParams;
  expect(first.getAll("action")).toEqual(["gate.approved", "gate.rejected", "gate.expired"]);
  expect(first.get("run_id")).toBe(RUN);

  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  await waitFor(() =>
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3),
  );
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
});

test("a run id is applied on Enter, and a partial one is refused on the field", async () => {
  api(() => json(page([created])));
  show();
  await screen.findByRole("table", { name: "Audit log" });

  const field = screen.getByRole("textbox", { name: "Run id" });
  fireEvent.change(field, { target: { value: "1a2b" } });
  fireEvent.submit(field);
  expect(screen.getByText("Enter a full run id.")).toBeTruthy();
  expect(field.getAttribute("aria-invalid")).toBe("true");
  expect(nav.replace).not.toHaveBeenCalled();

  fireEvent.change(field, { target: { value: ` ${RUN.toUpperCase()} ` } });
  fireEvent.submit(field);
  expect(nav.replace).toHaveBeenCalledWith(`/audit?run=${RUN}`, { scroll: false });
});

test("the category filter sets the URL", async () => {
  api(() => json(page([created])));
  show();
  await screen.findByRole("table", { name: "Audit log" });

  fireEvent.change(screen.getByRole("combobox", { name: "Category" }), {
    target: { value: "runs" },
  });
  expect(nav.replace).toHaveBeenCalledWith("/audit?category=runs", { scroll: false });
});
