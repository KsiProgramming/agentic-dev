import { expect, test, type Page } from "@playwright/test";

import { DOCS_DEMO, pretendConnections } from "./connections";
import {
  apiURL,
  COMBINE,
  DOCS_DEMO_URL,
  FAILING,
  REPO_READER,
  startReviewRun,
  startRun,
  GATE,
  MAP,
  SCANS,
  TYPED_WRITER,
  WRITER,
} from "./runs";

/** Every page renders in the shell with no horizontal page scroll (roadmap 2.2), and the main
 * nav is reachable: full sidebar from 1280 px, icon rail from 1024 px, a drawer below that. */

async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "page is wider than the viewport").toBeLessThanOrEqual(0);
}

async function expectNavReachable(page: Page) {
  const width = page.viewportSize()!.width;
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  const menuButton = page.getByRole("button", { name: "Open navigation" });
  if (width >= 1024) {
    await expect(sidebar.getByRole("link", { name: "Runs" })).toBeVisible();
    await expect(menuButton).toBeHidden();
    // The rail shows icons only; the full sidebar shows the labels.
    const label = sidebar.getByText("Templates", { exact: true });
    if (width >= 1280) await expect(label).toBeVisible();
    else await expect(label).toHaveClass(/sr-only/);
  } else {
    await expect(sidebar).toBeHidden();
    await menuButton.click();
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer.getByRole("link", { name: "Runs" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(menuButton).toBeFocused();
  }
}

/** Kept as a CI artifact (`layout-screenshots`) for review, not compared pixel by pixel. At
 * 375 px each screen is also taken in dark (`<name>-dark`): a PR that changes a screen attaches
 * its 1440 px light and 375 px dark views (design-language.md → How this is checked). */
async function screenshot(page: Page, name: string) {
  const project = test.info().project.name;
  const path = (suffix = "") => `test-results/screenshots/${project}/${name}${suffix}.png`;
  await page.screenshot({ path: path(), fullPage: true });
  if (project !== "mobile-375") return;
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await page.screenshot({ path: path("-dark"), fullPage: true });
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
}

async function checkPage(page: Page, name: string) {
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expectNoHorizontalScroll(page);
  await screenshot(page, name);
  await expectNavReachable(page);
}

test("/ redirects to runs", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/runs$/);
});

test("runs", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.getByRole("navigation", { name: "Views" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0); // the list has loaded
  await checkPage(page, "runs");
});

test("inbox, with a gate under review", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER, GATE], "E2E inbox layout");
  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await expect(review.getByRole("heading", { name: GATE.title })).toBeVisible({
    timeout: 30_000,
  });
  await checkPage(page, "inbox");
  await request.post(`${apiURL}/runs/${runId}/cancel`);
});

test("templates", async ({ page }) => {
  await page.goto("/templates");
  await expect(page.getByTestId("template-card").first()).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0); // the gallery has loaded
  await checkPage(page, "templates");
});

/** The sheet is a dialog over the page: it must fit the viewport too, and scroll inside. */
async function checkSheet(page: Page, name: string) {
  const sheet = page.getByTestId("new-run-sheet");
  await expect(sheet).toBeVisible();
  // Measure it where it rests, not while it slides in.
  await sheet.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  await expectNoHorizontalScroll(page);
  const box = (await sheet.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  await expect(sheet.getByRole("button", { name: "Start run" })).toBeInViewport();
  await screenshot(page, name);
}

test("the New run sheet, ready to start", async ({ page }) => {
  await page.goto("/templates?template=generate-docs");
  const sheet = page.getByTestId("new-run-sheet");
  await sheet.getByRole("combobox", { name: "Repository" }).click();
  await page.getByRole("option", { name: new RegExp(DOCS_DEMO) }).click();
  await sheet.getByLabel("Extra instructions (optional)").fill("Keep each page short.");
  await checkSheet(page, "new-run-sheet");
});

test("the New run sheet, before connecting", async ({ page }) => {
  await pretendConnections(page, "none");
  await page.goto("/templates?template=generate-docs");
  await expect(page.getByRole("button", { name: "Connect GitHub" })).toBeVisible();
  await checkSheet(page, "new-run-sheet-checklist");
});

/** The secondary nav sits beside the sub-page from 768 px and above it below that (11.7). */
async function expectSettingsLayout(page: Page) {
  const nav = (await page.getByRole("navigation", { name: "Settings" }).boundingBox())!;
  const content = (await page.getByRole("heading", { level: 2 }).first().boundingBox())!;
  if (page.viewportSize()!.width >= 768) expect(nav.x + nav.width).toBeLessThan(content.x);
  else expect(nav.y + nav.height).toBeLessThanOrEqual(content.y);
}

test("settings opens Integrations, keeping its query", async ({ page }) => {
  await page.goto("/settings?github=error&reason=denied");
  await expect(page).toHaveURL(/\/settings\/integrations\?github=error&reason=denied$/);
});

test("settings: integrations", async ({ page }) => {
  await page.goto("/settings/integrations");
  await expect(page.getByTestId("claude-status")).toBeVisible();
  await expect(page.getByTestId("github-status")).toBeVisible();
  await expectSettingsLayout(page);
  await checkPage(page, "settings-integrations");
});

test("settings: models and pricing", async ({ page }) => {
  await page.goto("/settings/models");
  const table = page.getByRole("table", { name: /Model prices/ });
  if (page.viewportSize()!.width >= 768) {
    await expect(table).toBeVisible();
    // Done when (11.7): the pricing table fits its card, with no scroll of its own.
    const overflow = await table.evaluate(
      (t) => t.parentElement!.scrollWidth - t.parentElement!.clientWidth,
    );
    expect(overflow, "pricing table scrolls sideways").toBeLessThanOrEqual(0);
  } else {
    await expect(table).toBeHidden();
    await expect(page.getByRole("list", { name: /Model prices/ })).toBeVisible();
  }
  await expectSettingsLayout(page);
  await checkPage(page, "settings-models");
});

test("settings: limits and budgets, with unsaved changes", async ({ page }) => {
  await page.goto("/settings/limits");
  await expect(page.getByTestId("limits-save-bar")).toBeHidden();
  await page.getByLabel("Loop iterations").fill("2");
  await expect(page.getByTestId("limits-save-bar")).toBeVisible();
  await expectSettingsLayout(page);
  await checkPage(page, "settings-limits");
});

test("audit log", async ({ page, request }) => {
  await startRun(request, [WRITER], "E2E audit layout");
  await page.goto("/audit");
  await expect(page.locator("[data-action]").filter({ visible: true }).first()).toBeVisible();
  await checkPage(page, "audit");
});

test("settings, not connected", async ({ page }) => {
  await pretendConnections(page, "none");
  await page.goto("/settings/integrations");
  await expect(page.getByLabel("Claude API key")).toBeVisible();
  await expect(page.getByRole("button", { name: "Install GitHub App" })).toBeVisible();
  await checkPage(page, "settings-not-connected");
});

test("settings, GitHub needs attention", async ({ page }) => {
  await pretendConnections(page, "github-gone");
  await page.goto("/settings/integrations");
  await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible();
  await checkPage(page, "settings-needs-attention");
});

test("a finished run", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER]);
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    {
      timeout: 30_000,
    },
  );
  await expect(page.getByRole("button", { name: "Rerun" })).toBeVisible();
  await checkPage(page, "run-finished");
});

test("an agent's activity, its work open", async ({ page, request }) => {
  const runId = await startRun(request, [REPO_READER], "E2E work layout", DOCS_DEMO_URL);
  await page.goto(`/runs/${runId}?step=reader&tab=activity`);
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    { timeout: 60_000 },
  );
  await page.getByTestId("work-block").getByRole("button").first().click();
  await expect(page.getByTestId("tool-intent").first()).toBeVisible();
  await checkPage(page, "run-activity");
});

test("a failed run", async ({ page, request }) => {
  const runId = await startRun(request, [FAILING]);
  await page.goto(`/runs/${runId}`);
  const banner = page.getByTestId("run-banner");
  await expect(banner).toHaveAttribute("data-kind", "failed", { timeout: 30_000 });
  // Done when (11.6): the failing step and its reason are seen without scrolling.
  await expect(banner).toContainText("Failed at broken");
  await expect(banner).toBeInViewport({ ratio: 1 });
  await checkPage(page, "run-failed");
});

test("a run failed at a typed port", async ({ page, request }) => {
  const runId = await startRun(request, [TYPED_WRITER], "E2E typed port layout");
  await page.goto(`/runs/${runId}`);
  const banner = page.getByTestId("run-banner");
  await expect(banner).toHaveAttribute("data-kind", "failed", { timeout: 30_000 });
  await expect(page.getByTestId("step-panel").getByTestId("port-errors")).toBeVisible();
  await checkPage(page, "run-port-failed");
});

test("a run's artifacts, and one open in its sheet", async ({ page, request }) => {
  const runId = await startRun(
    request,
    [{ ...TYPED_WRITER, writes: "findings.json" }],
    "E2E artifacts layout",
    undefined,
    '{"findings": [{"id": "F1"}]}',
  );
  await page.goto(`/runs/${runId}?view=artifacts`);
  await expect(page.getByTestId("run-artifact")).toBeVisible({ timeout: 30_000 });
  await checkPage(page, "run-artifacts");
  await page
    .getByTestId("run-artifact")
    .getByRole("button", { name: /findings\.json/ })
    .click();
  await expect(page.getByTestId("artifact-sheet").getByRole("group")).toBeVisible();
  await screenshot(page, "run-artifact-sheet");
});

test("a scan step's findings", async ({ page, request }) => {
  const runId = await startRun(request, SCANS, "E2E scan layout", DOCS_DEMO_URL);
  await page.goto(`/runs/${runId}?step=lint`);
  await expect(page.getByTestId("step-panel").getByTestId("findings-view")).toBeVisible({
    timeout: 60_000,
  });
  await checkPage(page, "run-scan-findings");
});

test("runs, with a run's menu open", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER]);
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    {
      timeout: 30_000,
    },
  );
  await page.goto("/runs");
  const row = page.locator(`[data-run-id="${runId}"]`).filter({ visible: true });
  await row.getByRole("button", { name: /^Actions for/ }).click();
  await expect(page.getByRole("menuitem", { name: "Rerun" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await screenshot(page, "runs-row-menu");
});

test("a run waiting at a gate", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER, GATE]);
  await page.goto(`/runs/${runId}`);
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 30_000 });
  await checkPage(page, "run-waiting");

  // The gate is visible without scrolling (roadmap 2.6): the whole dock is in the viewport,
  // its buttons included, and fits its width.
  const viewport = page.viewportSize()!;
  const box = (await dock.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  for (const name of [/Approve/, /Reject/, "Review details"]) {
    await expect(dock.getByRole("button", { name })).toBeInViewport({ ratio: 1 });
  }

  // Scrolled to the end, the selected step is above the dock, not under it.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const last = page.getByTestId("step-panel");
  const lastBox = (await last.boundingBox())!;
  const dockTop = (await dock.boundingBox())!.y;
  expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(dockTop + 1);
  await screenshot(page, "run-waiting-end");
});

test("a run's graph, waiting at a gate", async ({ page, request }) => {
  const runId = await startRun(request, [MAP, COMBINE, GATE]);
  await page.goto(`/runs/${runId}?view=graph`);
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("graph-node")).toHaveCount(4);
  await checkPage(page, "run-graph");

  // The graph pans and zooms in its own box, which ends above the dock once scrolled down.
  const graph = page.getByTestId("run-graph");
  const box = (await graph.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const scrolled = (await graph.boundingBox())!;
  expect(scrolled.y + scrolled.height).toBeLessThanOrEqual((await dock.boundingBox())!.y + 1);

  await page.locator('[data-testid="graph-node"][data-node-id="worker"]').click();
  await expect(page.getByTestId("step-panel")).toHaveAttribute("data-key", "each[1]/worker");
  await expectNoHorizontalScroll(page);
  await screenshot(page, "run-graph-step");

  // An event's payload opens in a drawer that fits the viewport.
  await page.getByRole("tab", { name: "Events" }).click();
  await page.getByTestId("event-row").first().getByRole("button").click();
  await expect(page.getByTestId("event-drawer")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await screenshot(page, "run-event-drawer");
});

test("the gate review sheet", async ({ page, request }) => {
  test.setTimeout(120_000);
  const runId = await startReviewRun(request, "E2E review layout");
  await page.goto(`/runs/${runId}`);
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 60_000 });
  await dock.getByRole("button", { name: "Review details" }).click();
  const review = page.getByTestId("gate-review");
  const diff = review.locator(".monaco-diff-editor");
  await expect(diff).toBeVisible({ timeout: 30_000 });

  // From 1024 px the files are listed beside a side-by-side diff; below, a picker sits above an
  // inline one. Either way the diff fits the viewport and scrolls in its own box.
  const viewport = page.viewportSize()!;
  if (viewport.width >= 1024) {
    await expect(review.getByRole("navigation", { name: "Changed files" })).toBeVisible();
    await expect(review.locator(".editor.original")).toBeVisible();
  } else {
    await expect(review.getByLabel(/File 1 of/)).toBeVisible();
  }
  const box = (await diff.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  await expect(review.getByRole("button", { name: /^Approve/ })).toBeInViewport({ ratio: 1 });
  await expectNoHorizontalScroll(page);
  await screenshot(page, "run-review");
  await page.keyboard.press("Escape");
  await request.post(`${apiURL}/runs/${runId}/cancel`);
});

test("an unknown run", async ({ page }) => {
  await page.goto("/runs/00000000-0000-0000-0000-000000000000");
  await expect(page.getByText("Run not found.")).toBeVisible();
  await checkPage(page, "run-not-found");
});
