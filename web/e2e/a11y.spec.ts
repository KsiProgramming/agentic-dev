import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// The API the browser talks to (compose publishes it on the host).
const apiURL = process.env.E2E_API_URL ?? "http://localhost:8000";

/** WCAG 2.2 AA, as the mission's UI quality target asks. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function startRun(request: APIRequestContext, steps: unknown[]): Promise<string> {
  const response = await request.post(`${apiURL}/runs`, {
    data: {
      workflow: {
        spec_version: "0",
        id: "e2e-a11y",
        name: "E2E a11y",
        root: { type: "sequence", id: "main", steps },
      },
      input: "hello",
    },
  });
  expect(response.status()).toBe(202);
  return ((await response.json()) as { run_id: string }).run_id;
}

const WRITER = { type: "agent", id: "writer", role: "Writer", instructions: "Say hello." };
const GATE = {
  type: "gate",
  id: "approve",
  title: "Approve the greeting",
  prompt: "Check it before the run ends.",
};

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

    test("home has no serious a11y issues", async ({ page }) => {
      await open(page, "/");
      await expect(page.getByRole("button", { name: "Start sample run" })).toBeVisible();
      await expect(page.getByRole("status")).toHaveCount(0); // the docs card has loaded
      await expectNoSeriousIssues(page);
    });

    test("settings has no serious a11y issues", async ({ page }) => {
      await open(page, "/settings");
      await expect(page.getByTestId("claude-status")).toBeVisible();
      await expect(page.getByTestId("github-status")).toBeVisible();
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
  });
}
