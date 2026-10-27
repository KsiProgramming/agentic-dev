import { expect, test } from "@playwright/test";

import { FAILING, startRun, WRITER } from "./runs";

/** Done when (11.6): from the runs list, one click shows an agent's output; a failed run names its
 * failing step and reason (the viewport checks are in layout.spec.ts); no JSON is shown inside a
 * table cell. */

test("from the runs list, one click shows an agent's output", async ({ page, request }) => {
  const name = `E2E console ${Date.now().toString(36)}`;
  const runId = await startRun(request, [WRITER], name);

  await page.goto("/runs");
  const row = page.locator(`[data-run-id="${runId}"]`).filter({ visible: true });
  await expect(row).toContainText("Succeeded", { timeout: 30_000 });
  await row.getByRole("link", { name }).click();

  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  const panel = page.getByTestId("step-panel");
  await expect(panel).toHaveAttribute("data-key", "writer");
  await expect(panel.getByRole("tab", { name: "Output" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByTestId("agent-message")).toBeVisible();
});

test("a failed run names its failing step and reason; Go to step selects it", async ({
  page,
  request,
}) => {
  const runId = await startRun(request, [FAILING]);
  await page.goto(`/runs/${runId}`);

  const banner = page.getByTestId("run-banner");
  await expect(banner).toHaveAttribute("data-kind", "failed", { timeout: 30_000 });
  await expect(banner).toContainText("Failed at broken");
  await banner.getByRole("button", { name: "Go to step" }).click();
  await expect(page).toHaveURL(/step=broken/);
  await expect(page.getByTestId("step-panel")).toHaveAttribute("data-key", "broken");
});

test("no table cell holds JSON; an event's payload opens in the drawer", async ({
  page,
  request,
}) => {
  const runId = await startRun(request, [WRITER]);
  await page.goto(`/runs/${runId}?tab=events`);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "succeeded", {
    timeout: 30_000,
  });
  await page.getByLabel("Step").selectOption("");
  await expect(page.getByTestId("event-row").first()).toBeVisible();

  const cells = await page.getByRole("cell").allTextContents();
  expect(cells.length).toBeGreaterThan(0);
  for (const cell of cells) expect(cell.trim()).not.toMatch(/^[[{]/);

  const started = page.locator('[data-testid="event-row"][data-type="run_started"]');
  await started.getByRole("button").click();
  const drawer = page.getByTestId("event-drawer");
  await expect(drawer.getByRole("group", { name: "Payload of event 1" })).toBeVisible();
});

test("the ⋯ menu downloads the run's events", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER]);
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "succeeded", {
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "More actions" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Download events" }).click();
  expect((await download).suggestedFilename()).toBe(`run-${runId.slice(0, 8)}-events.json`);
});
