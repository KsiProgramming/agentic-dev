import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { DOCS_DEMO, pretendConnections } from "./connections";
import { apiURL, COMBINE, GATE, MAP, startReviewRun, startRun, WRITER } from "./runs";

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
      await expect(page.getByRole("navigation", { name: "Views" })).toBeVisible();
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

    test("audit log has no serious a11y issues", async ({ page, request }) => {
      await startRun(request, [WRITER], "E2E audit a11y");
      await open(page, "/audit");
      await expect(page.locator("[data-action]").filter({ visible: true }).first()).toBeVisible();
      await expect(page.getByRole("status")).toHaveCount(0); // the log has loaded
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
      // In the page's content: Next's route announcer is an (empty) alert too.
      await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
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
      await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
        "data-status",
        "succeeded",
        {
          timeout: 30_000,
        },
      );
      await expectNoSeriousIssues(page);
    });

    test("a run waiting at a gate has no serious a11y issues", async ({ page, request }) => {
      const runId = await startRun(request, [WRITER, GATE]);
      await open(page, `/runs/${runId}`);
      const dock = page.getByTestId("approval-dock").filter({ visible: true });
      await expect(dock).toBeVisible({ timeout: 30_000 });
      await expectNoSeriousIssues(page);

      await dock.getByRole("button", { name: "Review details" }).click();
      await expect(page.getByTestId("gate-details")).toBeVisible();
      await expectNoSeriousIssues(page);
      await page.keyboard.press("Escape");

      await dock.getByRole("button", { name: /Reject/ }).click();
      await expect(page.getByRole("dialog", { name: /Reject/ })).toBeVisible();
      await expectNoSeriousIssues(page);
      await page.keyboard.press("Escape");
    });

    test("the gate review sheet has no serious a11y issues", async ({ page, request }) => {
      test.setTimeout(120_000);
      const runId = await startReviewRun(request, "E2E review a11y");
      await open(page, `/runs/${runId}`);
      const dock = page.getByTestId("approval-dock").filter({ visible: true });
      await expect(dock).toBeVisible({ timeout: 60_000 });

      await dock.getByRole("button", { name: "Review details" }).click();
      const review = page.getByTestId("gate-review");
      await expect(review.locator(".monaco-diff-editor")).toBeVisible({ timeout: 30_000 });
      // Scan once both editors are set up with their names, not while Monaco is still mounting.
      await expect(review.getByRole("textbox", { name: /, before$/ })).toBeAttached();
      await expect(review.getByRole("textbox", { name: /, after/ })).toBeAttached();
      await expectNoSeriousIssues(page);
      await page.keyboard.press("Escape");
      await request.post(`${apiURL}/runs/${runId}/cancel`);
    });

    test("a run's graph and a node's detail have no serious a11y issues", async ({
      page,
      request,
    }) => {
      const runId = await startRun(request, [MAP, COMBINE, GATE]);
      await open(page, `/runs/${runId}?tab=graph`);
      await expect(page.getByTestId("approval-dock").filter({ visible: true })).toBeVisible({
        timeout: 30_000,
      });
      await expect(page.getByTestId("graph-node")).toHaveCount(4);
      await expectNoSeriousIssues(page);

      await page.locator('[data-testid="graph-node"][data-node-id="worker"]').click();
      await expect(page.getByTestId("node-detail")).toBeVisible();
      await expectNoSeriousIssues(page);
      await page.keyboard.press("Escape");
    });

    test("a finished run's Rerun and the runs list menu have no serious a11y issues", async ({
      page,
      request,
    }) => {
      const runId = await startRun(request, [WRITER]);
      await open(page, `/runs/${runId}`);
      await expect(page.getByRole("button", { name: "Rerun" })).toBeVisible({ timeout: 30_000 });
      await expectNoSeriousIssues(page);
      await open(page, "/runs");
      const row = page.locator(`[data-run-id="${runId}"]`).filter({ visible: true });
      await row.getByRole("button", { name: /^Actions for/ }).click();
      await expect(page.getByRole("menuitem", { name: "Rerun" })).toBeVisible();
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

  test("a gate is decided from the keyboard: R opens Reject, Escape closes it, A approves", async ({
    page,
    request,
  }) => {
    const runId = await startRun(request, [WRITER, GATE]);
    await page.goto(`/runs/${runId}`);
    const dock = page.getByTestId("approval-dock").filter({ visible: true });
    await expect(dock).toBeVisible({ timeout: 30_000 });
    await expect(page).toHaveTitle(/^● Needs approval · Run /);

    await page.keyboard.press("r");
    const dialog = page.getByRole("dialog", { name: /Reject/ });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Comment (optional)")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    await page.keyboard.press("a");
    await expect(dock).toBeHidden({ timeout: 30_000 });
    await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
      "data-status",
      "succeeded",
      {
        timeout: 30_000,
      },
    );
    // Other runs may still wait, which prefixes "(N) ● Needs approval · "; this run no longer does.
    await expect(page).not.toHaveTitle(/^● Needs approval · Run /);
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
