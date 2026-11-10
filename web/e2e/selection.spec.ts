import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiURL, endedRunEvents, startRun } from "./runs";

/** A findings report the fake runtime echoes into `findings.json`: one high finding, which the
 * gate checks, and one low. */
const REPORT = JSON.stringify({
  scanner: "merged",
  checks: [{ path: ".", kind: "repo", tool: "agent", status: "ran" }],
  findings: [
    {
      fingerprint: "fp-high",
      tool: "agent",
      rule: "sql-injection",
      severity: "high",
      category: "security",
      path: "app/db.py",
      line: 12,
      message: "Query built from user input.",
    },
    {
      fingerprint: "fp-low",
      tool: "ruff",
      rule: "F401",
      severity: "low",
      category: "lint",
      path: "app/util.py",
      line: 3,
      message: "Unused import.",
    },
  ],
  counts: { critical: 0, high: 1, medium: 0, low: 1, info: 0 },
  truncated: false,
});

/** A scan that writes `findings.json`, the selection gate `pick` (6.7) that ends the run when
 * rejected, and the gate `fix`, whose input is what the run went on with. A gate rather than an
 * agent: the stack's fake runtime streams an echo a word every half second, and a findings report
 * is long; a gate shows its input at once (`GET /runs/{id}/gate`'s `artifact`). */
const SELECTING = [
  { type: "agent", id: "scan", role: "Scanner", instructions: "Scan.", writes: "findings.json" },
  {
    type: "gate",
    id: "pick",
    title: "Which findings should agents fix?",
    select: { artifact: "findings.json", preselect: 'item.severity == "high"' },
    on_reject: "end",
    writes: "selected-findings.json",
  },
  { type: "gate", id: "fix", title: "Approve the fixes" },
];

const TITLE = "Which findings should agents fix?";

/** The fingerprints the run went on with: the input of the gate after the selection, once the
 * run waits there. */
async function chosen(request: APIRequestContext, runId: string): Promise<string[]> {
  let artifact = "";
  await expect
    .poll(
      async () => {
        const response = await request.get(`${apiURL}/runs/${runId}/gate`);
        if (!response.ok()) return null;
        const gate = (await response.json()) as { node_id: string; artifact: string };
        artifact = gate.artifact;
        return gate.node_id;
      },
      { timeout: 30_000 },
    )
    .toBe("fix");
  const report = JSON.parse(artifact) as { findings: { fingerprint: string }[] };
  return report.findings.map((f) => f.fingerprint);
}

/** Done when (6.7, its gate): findings are chosen in the Inbox and the run goes on with those. */
test("findings are chosen at a selection gate in the Inbox", async ({ page, request }) => {
  const runId = await startRun(
    request,
    SELECTING,
    `Select ${Date.now().toString(36)}`,
    undefined,
    REPORT,
  );

  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await expect(review.getByRole("heading", { name: TITLE })).toBeVisible({ timeout: 30_000 });
  const rows = review.getByTestId("selection-item");
  await expect(rows).toHaveCount(2);
  await expect(review.getByText("1 of 2 selected")).toBeVisible();
  await expect(rows.nth(0)).toHaveAttribute("data-selected", "true");

  await review.getByRole("button", { name: "Clear" }).click();
  await expect(review.getByRole("button", { name: "Approve with 0 selected" })).toBeDisabled();
  await rows.nth(1).getByRole("checkbox").click();
  await review.getByRole("button", { name: "Approve with 1 selected" }).click();
  await expect(page.getByText(`Approved: ${TITLE}`)).toBeVisible();

  expect(await chosen(request, runId)).toEqual(["fp-low"]);
  const artifact = await request.get(`${apiURL}/runs/${runId}/artifacts/selected-findings.json`);
  expect(artifact.status()).toBe(200);
});

test("in the console, A opens the checklist and the keyboard approves", async ({
  page,
  request,
}) => {
  const runId = await startRun(
    request,
    SELECTING,
    `Select key ${Date.now().toString(36)}`,
    undefined,
    REPORT,
  );

  await page.goto(`/runs/${runId}`);
  const dock = page.getByTestId("approval-dock");
  await expect(dock.getByRole("button", { name: /Choose findings/ })).toBeVisible({
    timeout: 30_000,
  });
  await page.keyboard.press("a");
  const sheet = page.getByTestId("gate-selection");
  await expect(sheet.getByTestId("selection-item")).toHaveCount(2);

  // Keyboard only: Space toggles the focused checkbox.
  await sheet.getByRole("checkbox").nth(1).focus();
  await page.keyboard.press("Space");
  await expect(sheet.getByText("2 of 2 selected")).toBeVisible();
  await sheet.getByRole("button", { name: "Approve with 2 selected" }).click();

  expect(await chosen(request, runId)).toEqual(["fp-high", "fp-low"]);
});

test("ending the run at a selection gate completes it without the steps after", async ({
  page,
  request,
}) => {
  const runId = await startRun(
    request,
    SELECTING,
    `Select end ${Date.now().toString(36)}`,
    undefined,
    REPORT,
  );

  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await review.getByRole("button", { name: /End run here/ }).click({ timeout: 30_000 });
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("The run completes here, without the steps after the gate.");
  await dialog.getByRole("button", { name: "End run here" }).click();
  await expect(page.getByText(`Ended: ${TITLE}`)).toBeVisible();

  const events = await endedRunEvents(request, runId);
  expect(events.at(-1)?.type).toBe("run_completed");
  expect(events.some((e) => e.node_id === "fix")).toBe(false);
});

/** WCAG 2.2 AA, as in `a11y.spec.ts`. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

for (const colorScheme of ["light", "dark"] as const) {
  for (const width of [375, 1440]) {
    test(`the checklist has no serious a11y issues (${colorScheme}, ${width} px)`, async ({
      page,
      request,
    }) => {
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize({ width, height: 900 });
      const runId = await startRun(
        request,
        SELECTING,
        `Select a11y ${Date.now().toString(36)}`,
        undefined,
        REPORT,
      );

      await page.goto(`/runs/${runId}`);
      await page
        .getByTestId("approval-dock")
        .getByRole("button", { name: /Choose findings/ })
        .click({ timeout: 30_000 });
      const sheet = page.getByTestId("gate-selection");
      await expect(sheet.getByTestId("selection-item")).toHaveCount(2);
      // No horizontal page scroll at either width.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
      const serious = violations
        .filter((v) => v.impact === "serious" || v.impact === "critical")
        .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
      expect(serious).toEqual([]);
      await page.screenshot({
        path: `test-results/selection-${colorScheme}-${width}.png`,
        fullPage: false,
      });
    });
  }
}
