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
