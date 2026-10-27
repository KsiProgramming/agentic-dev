import { expect, test } from "@playwright/test";

import { DOCS_DEMO_URL, FAILING, REPO_READER, startRun, WRITER } from "./runs";

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

/** Done when (11.8): a finished run reads as one line of work and one visible answer per agent
 * turn; opening the work shows why each call was made; a live run shows the current step and an
 * elapsed time that ticks. */

test("a finished agent turn is one line of work and its answer; opening it shows why", async ({
  page,
  request,
}) => {
  const runId = await startRun(request, [REPO_READER], "E2E work block", DOCS_DEMO_URL);
  await page.goto(`/runs/${runId}?step=reader&tab=activity`);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "succeeded", {
    timeout: 60_000,
  });

  const panel = page.getByTestId("step-panel");
  const block = panel.getByTestId("work-block");
  await expect(block).toHaveCount(1);
  const header = block.getByRole("button").first();
  await expect(header).toHaveAttribute("aria-expanded", "false");
  await expect(header).toContainText("Listed 1 folder, read 1 file, ran 1 search");
  await expect(header).toContainText("3 tool calls");
  await expect(panel.getByTestId("agent-message")).toHaveText("hello");

  await header.click();
  await expect(panel.getByTestId("tool-intent")).toHaveText([
    "See how the repo is laid out",
    "Read the project settings",
    "Find the project table",
  ]);
  await expect(panel.getByTestId("reasoning")).toContainText("Look at the repository");
});

test("a live run shows what the agent is doing, with a timer that ticks", async ({
  page,
  request,
}) => {
  const runId = await startRun(request, [REPO_READER], "E2E live work", DOCS_DEMO_URL);
  await page.goto(`/runs/${runId}`);

  const live = page.locator('[data-testid="work-block"][data-live]').first();
  await expect(live).toBeVisible({ timeout: 60_000 });
  await expect(live.getByTestId("work-title")).toHaveText(/…$/);
  const elapsed = live.getByTestId("work-elapsed");
  const first = await elapsed.textContent();
  await expect(elapsed).not.toHaveText(first ?? "", { timeout: 3_000 });
});
