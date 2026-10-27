import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { apiURL, endedRunEvents, EXPIRING_GATE, startRun, WRITER } from "./runs";

/** Done when (11.3): a gate past its time to live cancels its run cleanly, drops out of every
 * waiting count and shows "Expired" with the reason. The e2e worker sweeps every second
 * (`GATE_SWEEP_S=1`). */
test("a gate nobody decides expires: the run is cancelled and shows Expired", async ({
  page,
  request,
}) => {
  const name = `Expires ${Date.now().toString(36)}`;
  const runId = await startRun(request, [WRITER, EXPIRING_GATE], name);

  await page.goto(`/runs/${runId}`);
  const dock = page.getByRole("region", { name: "Approval needed" });
  await expect(dock).toBeVisible({ timeout: 30_000 });
  await expect(dock.getByText(/^Expires in/)).toBeVisible();

  // The worker cancels the run once the gate's 8 s are up; the console follows live.
  const status = page.getByTestId("run-status");
  await expect(status).toHaveText("Expired", { timeout: 30_000 });
  await expect(status).toHaveAttribute("data-status", "cancelled");
  await expect(page.getByText(/Approval expired: nobody approved or rejected/)).toBeVisible();
  await expect(dock).toHaveCount(0);

  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);

  // Cleanly: through the cancel path, with the reason, and no decision was made.
  const events = await endedRunEvents(request, runId);
  expect(events.at(-1)).toMatchObject({
    type: "run_cancelled",
    payload: { reason: "Approval expired", expired: true },
  });
  expect(events.some((e) => e.type === "gate_decided")).toBe(false);
  const late = await request.post(`${apiURL}/runs/${runId}/approvals`, {
    data: { node_id: EXPIRING_GATE.id, decision: "approve" },
  });
  expect(late.status()).toBe(409);

  // No longer waiting anywhere: not among the runs that need approval, Expired in the list.
  await page.goto("/runs");
  const all = page.getByRole("table", { name: "All runs" });
  const row = all.locator(`[data-run-id="${runId}"]`);
  await expect(row).toContainText("Expired", { timeout: 15_000 });
  await expect(
    page
      .getByRole("table", { name: "Runs that need approval" })
      .locator(`[data-run-id="${runId}"]`),
  ).toHaveCount(0);
  const waiting = await request.get(`${apiURL}/runs`, { params: { status: "waiting" } });
  const ids = ((await waiting.json()) as { items: { id: string }[] }).items.map((r) => r.id);
  expect(ids).not.toContain(runId);
});
