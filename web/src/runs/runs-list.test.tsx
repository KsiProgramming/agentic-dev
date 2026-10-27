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

test("a waiting run offers Review, which opens its console; others do not", () => {
  show([runSummary({ id: "r-wait", status: "waiting" }), runSummary({ id: "r-done" })]);

  const table = within(screen.getByRole("table", { name: "Runs" }));
  const reviews = table.getAllByRole("link", { name: /^Review/ });
  expect(reviews).toHaveLength(1);
  expect(reviews[0]!.getAttribute("href")).toBe("/runs/r-wait");
  const cards = within(screen.getByRole("list", { name: "Runs" }));
  expect(cards.getAllByRole("link", { name: /^Review/ })).toHaveLength(1);
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
  const cards = within(screen.getByRole("list", { name: "Runs" }));
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
