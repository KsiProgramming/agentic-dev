import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { DOCS_DEMO, pretendConnections } from "./connections";
import { GATE, startRun, WRITER } from "./runs";

/** WCAG 2.2 AA, as the mission's UI quality target asks. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

/** Fails on serious or critical axe violations, listing each rule and the elements it hit. */
async function expectNoSeriousIssues(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const serious = violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(serious).toEqual([]);
}

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    /** Opens `path` and checks the theme follows the system setting before axe runs. */
    async function open(page: Page, path: string) {
      await page.goto(path);
      const html = page.locator("html");
      if (colorScheme === "dark") await expect(html).toHaveClass(/\bdark\b/);
      else await expect(html).not.toHaveClass(/\bdark\b/);
    }

    test("runs has no serious a11y issues", async ({ page }) => {
      await open(page, "/runs");
      await expect(page.getByRole("heading", { name: "All runs" })).toBeVisible();
      await expect(page.getByRole("status")).toHaveCount(0); // the list has loaded
      await expect(page.getByTestId("workspace-name")).toBeAttached();
      await expectNoSeriousIssues(page);
    });

    test("templates has no serious a11y issues", async ({ page }) => {
      await open(page, "/templates");
      await expect(page.getByTestId("template-card").first()).toBeVisible();
      await expect(page.getByRole("status")).toHaveCount(0); // the gallery has loaded
      await expectNoSeriousIssues(page);
    });

    test("the New run sheet has no serious a11y issues", async ({ page }) => {
      await open(page, "/templates?template=generate-docs");
      const sheet = page.getByTestId("new-run-sheet");
      await sheet.getByRole("combobox", { name: "Repository" }).click();
      await expect(page.getByRole("option", { name: new RegExp(DOCS_DEMO) })).toBeVisible();
      await expectNoSeriousIssues(page);
      await page.getByRole("option", { name: new RegExp(DOCS_DEMO) }).click();
      await sheet.getByLabel("Output dir (optional)").fill("not valid!");
      await sheet.getByRole("button", { name: "Start run" }).click();
      await expect(sheet.getByRole("alert")).toBeVisible();
      await expectNoSeriousIssues(page);
    });

    test("the New run checklist has no serious a11y issues", async ({ page }) => {
      await pretendConnections(page, "none");
      await open(page, "/templates?template=generate-docs");
      await page.getByRole("button", { name: "Add key" }).click();
      await expect(page.getByLabel("Claude API key")).toBeVisible();
      await expectNoSeriousIssues(page);
    });

    test("settings has no serious a11y issues", async ({ page }) => {
      await open(page, "/settings");
      await expect(page.getByTestId("claude-status")).toBeVisible();
      await expect(page.getByTestId("github-status")).toBeVisible();
      await page.getByRole("button", { name: /repositories accessible/ }).click();
      await expectNoSeriousIssues(page);
      await page.getByRole("button", { name: "Disconnect" }).click();
      await expect(page.getByRole("alertdialog")).toBeVisible();
      await expectNoSeriousIssues(page);
      await page.keyboard.press("Escape");
    });

    test("settings, not connected or needing attention, has no serious a11y issues", async ({
      page,
    }) => {
      await pretendConnections(page, "none");
      await open(page, "/settings");
      await page.getByRole("button", { name: "Save key" }).click();
      await expect(page.getByRole("alert")).toBeVisible();
      await expectNoSeriousIssues(page);
      await page.unrouteAll();
      await pretendConnections(page, "github-gone");
      await page.reload();
      await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible();
      await expectNoSeriousIssues(page);
    });

    test("a finished run has no serious a11y issues", async ({ page, request }) => {
      const runId = await startRun(request, [WRITER]);
      await open(page, `/runs/${runId}`);
      await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "succeeded", {
        timeout: 30_000,
      });
      await expectNoSeriousIssues(page);
    });

    test("a run waiting at a gate has no serious a11y issues", async ({ page, request }) => {
      const runId = await startRun(request, [WRITER, GATE]);
      await open(page, `/runs/${runId}`);
      await expect(page.getByTestId("gate-panel")).toBeVisible({ timeout: 30_000 });
      await expectNoSeriousIssues(page);
    });

    test("an unknown run has no serious a11y issues", async ({ page }) => {
      await open(page, "/runs/00000000-0000-0000-0000-000000000000");
      await expect(page.getByText("Run not found.")).toBeVisible();
      await expectNoSeriousIssues(page);
    });

    test("the open drawer has no serious a11y issues", async ({ page }) => {
      test.skip(page.viewportSize()!.width >= 1024, "the drawer is only used below 1024 px");
      await open(page, "/runs");
      await page.getByRole("button", { name: "Open navigation" }).click();
      await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();
      await expectNoSeriousIssues(page);
    });
  });
}

test.describe("keyboard", () => {
  test("the first Tab reaches the skip link, which moves focus to the content", async ({
    page,
  }) => {
    await page.goto("/runs");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#content")).toBeFocused();
  });

  test("the drawer keeps focus inside and gives it back on Escape", async ({ page }) => {
    test.skip(page.viewportSize()!.width >= 1024, "the drawer is only used below 1024 px");
    await page.goto("/runs");
    const button = page.getByRole("button", { name: "Open navigation" });
    await button.focus();
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("dialog", { name: "Navigation" });
    await expect(drawer).toBeVisible();

    for (let i = 0; i < 6; i++) {
      await page.keyboard.press("Tab");
      const inside = await drawer.evaluate((el) => el.contains(document.activeElement));
      expect(inside, `focus left the drawer after ${i + 1} Tab(s)`).toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(button).toBeFocused();
  });

  test("the theme menu works from the keyboard", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("button", { name: "Theme" }).focus();
    await page.keyboard.press("Enter");
    await page.getByRole("menuitemradio", { name: "Dark" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  });
});
