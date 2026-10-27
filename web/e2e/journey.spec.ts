import { expect, test, type Page } from "@playwright/test";

import { connectionsURL, DOCS_DEMO, TEST_KEY } from "./connections";
import { apiURL } from "./runs";

/**
 * Roadmap 2.6, end to end on the stack's fakes: a user connects Claude and GitHub, starts a docs
 * run, sees its gate without scrolling and rejects it, reruns it from the console and approves
 * the rerun, which opens a pull request, then reruns the first run from the runs list. Each
 * rerun links back to the run it repeats.
 *
 * It runs alone, after every other project (playwright.config.ts): it disconnects the
 * workspace first, which the other tests rely on.
 */
test.describe.configure({ mode: "serial" });

function runIdOf(page: Page): string {
  const id = new URL(page.url()).pathname.split("/").at(-1);
  if (!id) throw new Error(`not a run page: ${page.url()}`);
  return id;
}

/** `testId` on the page in view. Next keeps pages navigated away from mounted but hidden
 * (`cacheComponents`), so the earlier run's console is still in the DOM after a rerun. */
function shown(page: Page, testId: string) {
  return page.getByTestId(testId).filter({ visible: true });
}

async function expectDockInView(page: Page) {
  const dock = shown(page, "approval-dock");
  await expect(dock).toBeVisible({ timeout: 60_000 });
  await expect(dock).toBeInViewport({ ratio: 1 });
  return dock;
}

test("connect, start a docs run, reject, rerun and approve, rerun from the list", async ({
  page,
  request,
}) => {
  test.setTimeout(240_000);
  await request.delete(`${connectionsURL()}/claude`);
  await request.delete(`${connectionsURL()}/github`);

  // 1. Connect Claude and GitHub from Settings.
  await page.goto("/settings/integrations");
  await page.getByLabel("Claude API key").fill(TEST_KEY);
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByTestId("claude-status")).toContainText(`…${TEST_KEY.slice(-4)}`);
  await page.getByRole("button", { name: "Install GitHub App" }).click();
  await expect(page).toHaveURL(/\/settings\/integrations\?github=connected/);
  await expect(page.getByTestId("github-status")).toContainText("Installed on e2e-org");

  // 2. Start "Generate docs" on the fixture repo from the gallery.
  await page.goto("/templates");
  await page.getByRole("button", { name: "Start Generate docs" }).click();
  const sheet = page.getByTestId("new-run-sheet");
  await sheet.getByRole("combobox", { name: "Repository" }).click();
  await page.getByRole("option", { name: new RegExp(DOCS_DEMO) }).click();
  await sheet.getByRole("button", { name: "Start run" }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
  const first = runIdOf(page);

  // 3. The gate is in view without scrolling; reject it with a comment.
  let dock = await expectDockInView(page);
  await dock.getByRole("button", { name: /Reject/ }).click();
  const dialog = page.getByRole("dialog", { name: /Reject/ });
  await dialog.getByLabel("Comment (optional)").fill("Not this time.");
  await dialog.getByRole("button", { name: "Reject" }).click();
  await expect(shown(page, "run-status")).toHaveAttribute("data-status", "cancelled", {
    timeout: 60_000,
  });
  await expect(page.getByText(/Rejected: Not this time\./)).toBeVisible();

  // 4. Rerun it from the console: the rerun links back, waits at its gate, and is approved.
  await page.getByRole("button", { name: "Rerun" }).click();
  await expect(page).not.toHaveURL(new RegExp(first));
  const second = runIdOf(page);
  await expect(page.getByRole("link", { name: first.slice(0, 8) })).toHaveAttribute(
    "href",
    `/runs/${first}`,
  );
  dock = await expectDockInView(page);
  await dock.getByRole("button", { name: /Approve/ }).click();
  await expect(shown(page, "run-status")).toHaveAttribute("data-status", "succeeded", {
    timeout: 60_000,
  });
  await expect(shown(page, "pull-request")).toBeVisible();

  // 5. Rerun the first run from the runs list.
  await page.goto("/runs");
  const row = page.locator(`[data-run-id="${first}"]`).filter({ visible: true });
  await row.getByRole("button", { name: /^Actions for/ }).click();
  await page.getByRole("menuitem", { name: "Rerun" }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
  const third = runIdOf(page);
  expect([first, second]).not.toContain(third);
  await expect(page.getByRole("link", { name: first.slice(0, 8) })).toHaveAttribute(
    "href",
    `/runs/${first}`,
  );
  // Nothing is left waiting for whoever uses the stack next.
  await expectDockInView(page);
  await request.post(`${apiURL}/runs/${third}/cancel`);
});
