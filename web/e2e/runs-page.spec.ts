import { expect, test, type Locator } from "@playwright/test";

import { apiURL, FAILING, GATE, startRun, WRITER } from "./runs";

/** One run's row in a runs table. */
function row(table: Locator, runId: string): Locator {
  return table.locator(`[data-run-id="${runId}"]`);
}

/** Done when (2.4): the user finds any past run and sees whether it succeeded, failed or is
 * waiting. */
test("the runs page shows each run's outcome, waiting runs first, live", async ({
  page,
  request,
}) => {
  const tag = Date.now().toString(36);
  const ok = await startRun(request, [WRITER], `Succeeds ${tag}`);
  const bad = await startRun(request, [FAILING], `Fails ${tag}`);
  const gated = await startRun(request, [WRITER, GATE], `Waits ${tag}`);

  await page.goto("/");
  await expect(page).toHaveURL(/\/runs$/);
  const all = page.getByRole("table", { name: "All runs" });
  const waiting = page.getByRole("table", { name: "Runs that need approval" });
  await expect(row(all, ok)).toContainText("Succeeded", { timeout: 30_000 });
  await expect(row(all, bad)).toContainText("Failed", { timeout: 30_000 });
  await expect(row(all, gated)).toContainText("Waiting", { timeout: 30_000 });

  // What needs the user comes first.
  await expect(row(waiting, gated)).toBeVisible();
  const [waitingBox, allBox] = await Promise.all([waiting.boundingBox(), all.boundingBox()]);
  expect(waitingBox!.y).toBeLessThan(allBox!.y);

  // A status filter is kept in the URL, so it survives a reload.
  await page.getByRole("button", { name: /^Status:/ }).click();
  await page.getByRole("menuitemcheckbox", { name: "Failed" }).click();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/status=failed/);
  await expect(row(all, bad)).toBeVisible();
  await expect(row(all, ok)).toHaveCount(0);
  await page.reload();
  await expect(row(all, bad)).toBeVisible();
  await expect(page.getByRole("button", { name: "Status: Failed" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL(/\/runs$/);

  // Approving elsewhere updates the list with no reload.
  await expect(row(waiting, gated)).toBeVisible();
  const approval = await request.post(`${apiURL}/runs/${gated}/approvals`, {
    data: { node_id: GATE.id, decision: "approve" },
  });
  expect(approval.status()).toBe(202);
  await expect(row(all, gated)).toContainText("Succeeded", { timeout: 15_000 });
  await expect(row(waiting, gated)).toHaveCount(0);

  // A row opens the run.
  await row(all, bad)
    .getByRole("link", { name: `Fails ${tag}` })
    .click();
  await expect(page).toHaveURL(new RegExp(`/runs/${bad}$`));
});

/** Done when (11.2): a run that waits at a gate and works shows its active time, with the wait
 * apart, in the runs list and the console header. */
test("a run's wait at a gate is shown apart from its duration", async ({ page, request }) => {
  const tag = Date.now().toString(36);
  const gated = await startRun(request, [WRITER, GATE], `Waits then works ${tag}`);

  await page.goto(`/runs/${gated}`);
  const time = page.getByTestId("run-time");
  await expect(time).toContainText("waiting", { timeout: 30_000 });
  await page.waitForTimeout(2_000);
  const approval = await request.post(`${apiURL}/runs/${gated}/approvals`, {
    data: { node_id: GATE.id, decision: "approve" },
  });
  expect(approval.status()).toBe(202);
  await expect(page.getByTestId("run-status")).toContainText("Succeeded", { timeout: 30_000 });
  await expect(time).toHaveText(/^(<1s|\d+s) · waited \d+s$/);

  await page.goto("/runs");
  const all = page.getByRole("table", { name: "All runs" });
  await expect(row(all, gated).getByTestId("run-time")).toHaveText(/^(<1s|\d+s) · waited \d+s$/);
});

test("a run that waited 1 h and worked 2 min reads 2m 00s · waited 1h 00m", async ({ page }) => {
  const run = {
    id: "00000000-0000-4000-8000-0000000011a2",
    workspace_id: "00000000-0000-0000-0000-000000000001",
    status: "completed",
    workflow: { id: "generate-docs", name: "Waited an hour" },
    template_id: null,
    repo: null,
    created_at: "2026-10-27T09:00:00Z",
    started_at: "2026-10-27T09:00:00Z",
    finished_at: "2026-10-27T10:02:00Z",
    duration_ms: 3_720_000,
    active_ms: 120_000,
    waiting_ms: 3_600_000,
    measured_at: "2026-10-27T10:02:00Z",
    pr_url: null,
    waiting_gate: null,
    rerun_of: null,
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      estimated_usd: 0,
      cost_complete: true,
      budget_usd: null,
    },
  };
  await page.route(
    // Only the API's /runs: the page itself is also at /runs.
    (url) => url.origin === new URL(apiURL).origin && url.pathname === "/runs",
    (route) => route.fulfill({ json: { items: [run], next_cursor: null } }),
  );

  await page.goto("/runs");
  const all = page.getByRole("table", { name: "All runs" });
  await expect(row(all, run.id).getByTestId("run-time")).toHaveText("2m 00s · waited 1h 00m");
});
