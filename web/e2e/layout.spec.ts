import { expect, test, type Page } from "@playwright/test";

import { DOCS_DEMO, pretendConnections } from "./connections";
import { COMBINE, startRun, GATE, MAP, WRITER } from "./runs";

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

/** Kept as a CI artifact (`layout-screenshots`) for review, not compared pixel by pixel. */
async function screenshot(page: Page, name: string) {
  const project = test.info().project.name;
  await page.screenshot({
    path: `test-results/screenshots/${project}/${name}.png`,
    fullPage: true,
  });
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
  await expect(page.getByRole("heading", { name: "All runs" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0); // the list has loaded
  await checkPage(page, "runs");
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

test("settings", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("claude-status")).toBeVisible();
  await expect(page.getByTestId("github-status")).toBeVisible();
  await checkPage(page, "settings");
});

test("settings, not connected", async ({ page }) => {
  await pretendConnections(page, "none");
  await page.goto("/settings");
  await expect(page.getByLabel("Claude API key")).toBeVisible();
  await expect(page.getByRole("button", { name: "Install GitHub App" })).toBeVisible();
  await checkPage(page, "settings-not-connected");
});

test("settings, GitHub needs attention", async ({ page }) => {
  await pretendConnections(page, "github-gone");
  await page.goto("/settings");
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

  // Scrolled to the end, the last of the timeline is above the dock, not under it.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const last = page.getByTestId("step").last();
  const lastBox = (await last.boundingBox())!;
  const dockTop = (await dock.boundingBox())!.y;
  expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(dockTop + 1);
  await screenshot(page, "run-waiting-end");
});

test("a run's graph, waiting at a gate", async ({ page, request }) => {
  const runId = await startRun(request, [MAP, COMBINE, GATE]);
  await page.goto(`/runs/${runId}?tab=graph`);
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
  await expect(page.getByTestId("node-detail")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await screenshot(page, "run-graph-detail");
});

test("an unknown run", async ({ page }) => {
  await page.goto("/runs/00000000-0000-0000-0000-000000000000");
  await expect(page.getByText("Run not found.")).toBeVisible();
  await checkPage(page, "run-not-found");
});
