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
  expect(table.getByRole("link", { name: FAILED.id.slice(0, 8) }).getAttribute("href")).toBe(
    `/runs/${FAILED.id}`,
  );
  expect(table.getByText(/Rerun of/)).toBeDefined();
});
