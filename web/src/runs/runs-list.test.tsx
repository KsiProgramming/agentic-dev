import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, requested, stubApi } from "@/testing/api";

import { RunsList } from "./runs-list";
import { runSummary } from "./testing";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: navigation.push }) }));

const FAILED = runSummary({ id: "00000000-0000-0000-0000-0000000000f1", status: "failed" });
const NEW_ID = "00000000-0000-0000-0000-0000000000f2";

beforeEach(() => navigation.push.mockReset());
afterEach(() => vi.unstubAllGlobals());

function show(runs = [FAILED]) {
  return renderWithQueries(
    <RunsList runs={runs} now={Date.now()} label="Runs" baseUrl="http://api.test" />,
  );
}

test("a waiting run's status badge opens its review; there is no Review button", () => {
  show([runSummary({ id: "r-wait", status: "waiting" }), runSummary({ id: "r-done" })]);

  const table = within(screen.getByRole("table", { name: "Runs" }));
  const reviews = table.getAllByRole("link", { name: /: review/ });
  expect(reviews).toHaveLength(1);
  expect(reviews[0]!.getAttribute("href")).toBe("/runs/r-wait");
  expect(reviews[0]!.textContent).toMatch(/^Waiting/);
  expect(table.queryByRole("link", { name: /^Review/ })).toBeNull();
  const cards = within(screen.getByRole("list", { name: /^Runs/ }));
  expect(cards.getAllByRole("link", { name: /: review/ })).toHaveLength(1);
});

test("the Run column shows the workflow, the short id and what started the run", () => {
  show([
    runSummary({ id: "0123456789abcdef", trigger: "manual" }),
    runSummary({ id: "fedcba9876543210", trigger: "api" }),
  ]);

  const rows = within(screen.getByRole("table", { name: "Runs" })).getAllByRole("row");
  const manual = within(rows.find((r) => r.dataset.runId === "0123456789abcdef")!);
  expect(manual.getByRole("link", { name: "Generate docs" }).getAttribute("href")).toBe(
    "/runs/0123456789abcdef",
  );
  expect(manual.getByText("01234567")).toBeTruthy();
  expect(manual.getByText("Manual")).toBeTruthy();
  // The id is a value in a list row: it adds no tab stop.
  expect(manual.queryByRole("button", { name: /^Copy/ })).toBeNull();
  const api = within(rows.find((r) => r.dataset.runId === "fedcba9876543210")!);
  expect(api.getByText("API")).toBeTruthy();
});

test("the branch sits under the repo when the run is on one", () => {
  show([
    runSummary({ id: "on-branch", branch: "release/1.2" }),
    runSummary({ id: "on-default", branch: null }),
  ]);

  const rows = within(screen.getByRole("table", { name: "Runs" })).getAllByRole("row");
  const onBranch = rows.find((r) => r.dataset.runId === "on-branch")!;
  expect(onBranch.textContent).toContain("acme/docs");
  expect(within(onBranch).getByText("release/1.2")).toBeTruthy();
  expect(rows.find((r) => r.dataset.runId === "on-default")!.textContent).not.toContain("Branch");
});

test("rows are grouped under date headers, newest first", () => {
  const now = Date.parse("2026-10-27T15:00:00Z");
  renderWithQueries(
    <RunsList
      runs={[
        runSummary({ id: "today", created_at: "2026-10-27T09:00:00Z" }),
        runSummary({ id: "today-2", created_at: "2026-10-27T00:10:00Z" }),
        runSummary({ id: "yesterday", created_at: "2026-10-26T23:00:00Z" }),
        runSummary({ id: "week", created_at: "2026-10-22T12:00:00Z" }),
        runSummary({ id: "earlier", created_at: "2026-10-01T12:00:00Z" }),
      ]}
      now={now}
      label="Runs"
      baseUrl="http://api.test"
    />,
  );

  const table = screen.getByRole("table", { name: "Runs" });
  const headers = within(table).getAllByRole("rowheader");
  expect(headers.map((h) => h.textContent)).toEqual(["Today", "Yesterday", "This week", "Earlier"]);
  const today = table.querySelector('[data-date-group="Today"]')!;
  expect(
    [...today.querySelectorAll("[data-run-id]")].map((r) => r.getAttribute("data-run-id")),
  ).toEqual(["today", "today-2"]);
  expect(screen.getByRole("list", { name: "Runs, Earlier" })).toBeTruthy();
});

test.each([
  ["failed", true],
  ["cancelled", true],
  ["completed", true],
  ["running", false],
  ["queued", false],
  ["waiting", false],
] as const)("a %s run has a Rerun menu: %s", (status, shown) => {
  show([runSummary({ status })]);

  const table = within(screen.getByRole("table", { name: "Runs" }));
  expect(table.queryAllByRole("button", { name: /^Actions for/ })).toHaveLength(shown ? 1 : 0);
});

test("Rerun from the row menu starts the rerun and opens it", async () => {
  const fetch = stubApi({
    [`POST /runs/${FAILED.id}/rerun`]: () =>
      json(202, { run_id: NEW_ID, status: "queued", events_url: "" }),
  });
  show();

  const table = within(screen.getByRole("table", { name: "Runs" }));
  const trigger = table.getByRole("button", { name: /^Actions for/ });
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Rerun" }));

  await waitFor(() => expect(navigation.push).toHaveBeenCalledWith(`/runs/${NEW_ID}`));
  expect(requested(fetch)).toEqual([`POST /runs/${FAILED.id}/rerun`]);
});

test("a rerun links back to the run it repeats", () => {
  show([runSummary({ id: NEW_ID, rerun_of: FAILED.id })]);

  const table = within(screen.getByRole("table", { name: "Runs" }));
  expect(
    table.getByRole("link", { name: `Run ${FAILED.id.slice(0, 8)}` }).getAttribute("href"),
  ).toBe(`/runs/${FAILED.id}`);
  expect(table.getByText(/Rerun of/)).toBeDefined();
});

test("Done when (11.2): a run that waited 1 h and worked 2 min shows both apart", () => {
  const run = runSummary({
    started_at: "2026-10-22T10:00:00Z",
    finished_at: "2026-10-22T11:02:00Z",
    duration_ms: 3_720_000,
    active_ms: 120_000,
    waiting_ms: 3_600_000,
  });
  show([run]);

  const table = within(screen.getByRole("table", { name: "Runs" }));
  expect(table.getByTestId("run-time").textContent).toBe("2m 00s · waited 1h 00m");
  const cards = within(screen.getByRole("list", { name: /^Runs/ }));
  expect(cards.getByTestId("run-time").textContent).toBe("2m 00s · waited 1h 00m");
});

test("a waiting run's wait is live; a run that never waited shows its duration alone", () => {
  const now = Date.parse("2026-10-22T10:10:00Z");
  renderWithQueries(
    <RunsList
      runs={[
        runSummary({
          id: "r-wait",
          status: "waiting",
          finished_at: null,
          active_ms: 90_000,
          waiting_ms: 0,
          measured_at: "2026-10-22T10:05:00Z",
        }),
        runSummary({ id: "r-done" }),
      ]}
      now={now}
      label="Runs"
      baseUrl="http://api.test"
    />,
  );

  const table = within(screen.getByRole("table", { name: "Runs" }));
  expect(table.getAllByTestId("run-time").map((cell) => cell.textContent)).toEqual([
    "1m 30s · waiting 5m 00s",
    "2m 05s",
  ]);
});

test("a run whose approval expired shows Expired, in Cancelled's grey", () => {
  show([
    runSummary({
      id: "r-exp",
      status: "cancelled",
      expired: true,
      cancel_reason: "Approval expired",
    }),
  ]);

  const table = within(screen.getByRole("table", { name: "Runs" }));
  const badge = table.getByText("Expired");
  expect(badge.closest("[data-status]")?.getAttribute("data-status")).toBe("cancelled");
  expect(table.queryByRole("link", { name: /: review/ })).toBeNull();
});
