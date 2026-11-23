import { expect, test } from "@playwright/test";

import { DOCS_DEMO_URL, endedRunEvents, REPEAT_REASON, REPEATER, startRun } from "./runs";

/** Done when (13.7): an agent that repeats the same failing call is paused by the repeat breaker
 * and goes on once a person resumes it. The stack's fake agent for `[fake:repeat-failing-call]`
 * reads a missing file until it is stopped, and answers once it was told why it was paused. */

test("a run paused by the repeat breaker shows why, and Resume lets it go on", async ({
  page,
  request,
}) => {
  const name = `Breaker ${Date.now().toString(36)}`;
  const runId = await startRun(request, [REPEATER], name, DOCS_DEMO_URL);

  await page.goto(`/runs/${runId}`);
  const status = page.getByTestId("run-status");
  await expect(status).toHaveText("Paused", { timeout: 60_000 });
  await expect(status).toHaveAttribute("data-status", "waiting");
  const banner = page.getByTestId("run-banner");
  await expect(banner).toHaveAttribute("data-kind", "paused");
  await expect(banner).toContainText(`Paused by a circuit breaker: ${REPEAT_REASON}`);
  await expect(page.getByTestId("run-breakers")).toHaveText("1");
  await expect(page).toHaveTitle(/^● Paused · /);

  // The tripped step says what it saw.
  const details = page.getByTestId("breaker-details").first();
  await expect(details).toContainText("3 errors, reached 3");
  await expect(details).toContainText("repo.read_file");

  const dock = page.getByRole("region", { name: "Paused by a circuit breaker" });
  await dock.getByRole("button", { name: /Resume/ }).click();
  await expect(page.getByText("Resumed: ")).toBeVisible();
  await expect(status).toHaveText("Succeeded", { timeout: 60_000 });

  // The resumed agent was told why, and the step that tripped ran again from its start.
  const events = await endedRunEvents(request, runId);
  expect(events.find((e) => e.type === "gate_decided")).toMatchObject({
    node_id: "repeater",
    payload: { decision: "approve", source: "breaker" },
  });
  const starts = events.filter((e) => e.type === "node_started" && e.node_id === "repeater");
  expect(starts.at(-1)?.payload.resumed_after).toMatchObject({ breaker: "repeat" });
  expect(events.filter((e) => e.type === "breaker_tripped")).toHaveLength(1);
  expect(events.at(-1)?.type).toBe("run_completed");
});

test("Cancel run asks first, then ends the paused run", async ({ page, request }) => {
  const runId = await startRun(
    request,
    [REPEATER],
    `Breaker cancel ${Date.now().toString(36)}`,
    DOCS_DEMO_URL,
  );

  await page.goto(`/runs/${runId}`);
  const dock = page.getByRole("region", { name: "Paused by a circuit breaker" });
  await expect(dock).toBeVisible({ timeout: 60_000 });
  await dock.getByRole("button", { name: /Cancel run/ }).click();
  const dialog = page.getByRole("dialog", { name: "Cancel this run?" });
  await expect(dialog).toBeVisible();
  // Nothing was decided before the dialog was confirmed.
  expect((await endedRunEvents(request, runId)).some((e) => e.type === "gate_decided")).toBe(false);
  await dialog.getByRole("button", { name: "Cancel run" }).click();

  await expect(page.getByTestId("run-status")).toHaveText("Cancelled", { timeout: 30_000 });
  const events = await endedRunEvents(request, runId);
  expect(events.at(-1)).toMatchObject({
    type: "run_cancelled",
    payload: { reason: "Cancelled after a circuit breaker" },
  });
});

test("the Inbox lists a paused run with what tripped, and Resume goes on", async ({
  page,
  request,
}) => {
  const name = `Breaker inbox ${Date.now().toString(36)}`;
  const runId = await startRun(request, [REPEATER], name, DOCS_DEMO_URL);

  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await expect(review.getByTestId("breaker-details")).toBeVisible({ timeout: 60_000 });
  await expect(review.getByRole("heading", { level: 2 })).toContainText("Paused:");
  await review.getByRole("button", { name: /Resume/ }).click();
  await expect(page.getByText(/^Resumed: /)).toBeVisible();

  const events = await endedRunEvents(request, runId);
  expect(events.at(-1)?.type).toBe("run_completed");
});
