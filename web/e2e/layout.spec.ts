import { expect, test, type Page } from "@playwright/test";

import { startRun, GATE, WRITER } from "./runs";

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
  await expect(page.getByRole("link", { name: "Browse templates" })).toBeVisible();
  await checkPage(page, "runs");
});

test("templates", async ({ page }) => {
  await page.goto("/templates");
  await expect(page.getByRole("button", { name: "Start sample run" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveCount(0); // the docs card has loaded
  await checkPage(page, "templates");
});

test("settings", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("claude-status")).toBeVisible();
  await expect(page.getByTestId("github-status")).toBeVisible();
  await checkPage(page, "settings");
});

test("a finished run", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER]);
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "succeeded", {
    timeout: 30_000,
  });
  await checkPage(page, "run-finished");
});

test("a run waiting at a gate", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER, GATE]);
  await page.goto(`/runs/${runId}`);
  await expect(page.getByTestId("gate-panel")).toBeVisible({ timeout: 30_000 });
  await checkPage(page, "run-waiting");
});

test("an unknown run", async ({ page }) => {
  await page.goto("/runs/00000000-0000-0000-0000-000000000000");
  await expect(page.getByText("Run not found.")).toBeVisible();
  await checkPage(page, "run-not-found");
});
