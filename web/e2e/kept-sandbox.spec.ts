import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { DOCS_DEMO_URL, FAILING, REPO_WRITER, startRun } from "./runs";

/** Done when (12.3): a failed run's console shows what its writers changed and until when its
 * sandbox is kept; once swept, the console says so and the changes are still shown. The e2e
 * worker sweeps every second (`SANDBOX_SWEEP_S=1`); the sandbox is removed on request, as its
 * 24 h are too long to wait for. */
test("a failed run keeps its sandbox, shows its writer's changes, and keeps them once swept", async ({
  page,
  request,
}) => {
  const name = `Kept ${Date.now().toString(36)}`;
  const runId = await startRun(request, [REPO_WRITER, FAILING], name, DOCS_DEMO_URL);
  await page.goto(`/runs/${runId}`);

  await expect(page.getByTestId("run-banner")).toHaveAttribute("data-kind", "failed", {
    timeout: 60_000,
  });
  const line = page.getByTestId("run-sandbox");
  await expect(line).toHaveAttribute("data-state", "kept", { timeout: 30_000 });
  await expect(line).toContainText("Sandbox kept");
  await expect(line.getByText(/^Expires in 2[34] h$/)).toBeVisible();

  await line.getByRole("button", { name: "View changes" }).click();
  const sheet = page.getByTestId("gate-review");
  await expect(sheet.getByRole("heading", { name: "What the writers changed" })).toBeVisible();
  await expect(sheet.getByText("NOTES.md").first()).toBeVisible();
  expect(
    (await new AxeBuilder({ page }).include("[data-testid=gate-review]").analyze()).violations,
  ).toEqual([]);
  await page.keyboard.press("Escape");

  await line.getByRole("button", { name: "Remove sandbox now" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove sandbox" }).click();
  // The worker removes it within a second; the line reads the run again every 15 s.
  await expect(line).toHaveAttribute("data-state", "removed", { timeout: 45_000 });
  await expect(line).toContainText("Sandbox removed");

  await line.getByRole("button", { name: "View changes" }).click();
  await expect(sheet.getByText("NOTES.md").first()).toBeVisible();
});
