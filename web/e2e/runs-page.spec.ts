import { expect, test, type Locator } from "@playwright/test";

import { apiURL, FAILING, GATE, startRun, WRITER } from "./runs";
import { E2E_WORKSPACE_NAME, e2eWorkspaceId } from "./workspace";

/** The API's default workspace, where real runs go. */
const DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001";

/** One run's row in a runs table. */
function row(table: Locator, runId: string): Locator {
  return table.locator(`[data-run-id="${runId}"]`);
}

/** Done when (2.4 and 11.4): the user finds any past run and sees whether it succeeded, failed
 * or is waiting; real runs are the first rows whatever is waiting, and a waiting run is one click
 * away. */
test("the runs page lists every run under its views, a waiting run one click away", async ({
  page,
  request,
}) => {
  const tag = Date.now().toString(36);
  const ok = await startRun(request, [WRITER], `Succeeds ${tag}`);
  const bad = await startRun(request, [FAILING], `Fails ${tag}`);
  const gated = await startRun(request, [WRITER, GATE], `Waits ${tag}`);

  await page.goto("/");
  await expect(page).toHaveURL(/\/runs$/);
  const all = page.getByRole("table", { name: "All runs" });
  await expect(row(all, ok)).toContainText("Succeeded", { timeout: 30_000 });
  await expect(row(all, bad)).toContainText("Failed", { timeout: 30_000 });
  await expect(row(all, gated)).toContainText("Waiting", { timeout: 30_000 });

  // Nothing is pinned above the list: the waiting run is a row among the others, under Today.
  await expect(page.getByRole("table")).toHaveCount(1);
  const today = all.locator('[data-date-group="Today"]');
  for (const id of [ok, bad, gated]) await expect(row(today, id)).toBeVisible();
  await expect(row(all, ok)).toContainText(`Succeeds ${tag}`);
  await expect(row(all, ok)).toContainText(ok.slice(0, 8));
  await expect(row(all, ok)).toContainText("API");

  // One click to what waits: the Needs approval view, counted on its tab and kept in the URL.
  const views = page.getByRole("navigation", { name: "Views" });
  const needsApproval = views.getByRole("link", { name: /^Needs approval/ });
  await expect(needsApproval).toHaveText(/Needs approval\s*,?\s*[1-9]\d*/);
  await needsApproval.click();
  await expect(page).toHaveURL(/view=waiting/);
  await expect(needsApproval).toHaveAttribute("aria-current", "page");
  const waiting = page.getByRole("table", { name: "Needs approval runs" });
  await expect(row(waiting, gated)).toBeVisible();
  await expect(row(waiting, ok)).toHaveCount(0);
  await page.reload();
  await expect(row(waiting, gated)).toBeVisible();

  // Its status badge opens the review.
  await row(waiting, gated)
    .getByRole("link", { name: /: review/ })
    .click();
  await expect(page).toHaveURL(new RegExp(`/runs/${gated}$`));
  await page.goBack();

  // Approving elsewhere takes it out of the view with no reload.
  await expect(row(waiting, gated)).toBeVisible();
  const approval = await request.post(`${apiURL}/runs/${gated}/approvals`, {
    data: { node_id: GATE.id, decision: "approve" },
  });
  expect(approval.status()).toBe(202);
  await expect(row(waiting, gated)).toHaveCount(0, { timeout: 15_000 });

  // The Failed view, and a row opens the run.
  await views.getByRole("link", { name: /^Failed/ }).click();
  await expect(page).toHaveURL(/view=failed/);
  const failed = page.getByRole("table", { name: "Failed runs" });
  await expect(row(failed, ok)).toHaveCount(0);
  await row(failed, bad)
    .getByRole("link", { name: `Fails ${tag}` })
    .click();
  await expect(page).toHaveURL(new RegExp(`/runs/${bad}$`));
});

/** Done when (11.4): no test run appears in the default workspace. */
test("runs the e2e tests start stay out of the default workspace", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER], `Kept apart ${Date.now().toString(36)}`);
  const listed = async (workspaceId: string) => {
    const response = await request.get(`${apiURL}/runs`, {
      params: { workspace_id: workspaceId, limit: 100 },
    });
    expect(response.status()).toBe(200);
    return ((await response.json()) as { items: { id: string }[] }).items.map((r) => r.id);
  };

  expect(await listed(e2eWorkspaceId())).toContain(runId);
  const inDefault = await listed(DEFAULT_WORKSPACE_ID);
  expect(inDefault).not.toContain(runId);
  // A fresh stack (CI) has no run in the default workspace at all.
  if (process.env.CI) expect(inDefault).toEqual([]);

  // The browser opens the E2E workspace, where the run is listed.
  await page.goto("/runs");
  await expect(page.getByTestId("workspace-name").first()).toHaveText(E2E_WORKSPACE_NAME);
  await expect(row(page.getByRole("table", { name: "All runs" }), runId)).toBeVisible();
});

/** Done when (11.2): a run that waits at a gate and works shows its active time, with the wait
 * apart, in the runs list and the console header. */
test("a run's wait at a gate is shown apart from its duration", async ({ page, request }) => {
  const tag = Date.now().toString(36);
  const gated = await startRun(request, [WRITER, GATE], `Waits then works ${tag}`);

  await page.goto(`/runs/${gated}`);
  const time = page.getByTestId("run-time");
  await expect(time).toContainText("waiting", { timeout: 30_000 });
  await page.waitForTimeout(2_000);
  const approval = await request.post(`${apiURL}/runs/${gated}/approvals`, {
    data: { node_id: GATE.id, decision: "approve" },
  });
  expect(approval.status()).toBe(202);
  await expect(page.getByTestId("run-status")).toContainText("Succeeded", { timeout: 30_000 });
  await expect(time).toHaveText(/^(<1s|\d+s) · waited \d+s$/);

  await page.goto("/runs");
  const all = page.getByRole("table", { name: "All runs" });
  await expect(row(all, gated).getByTestId("run-time")).toHaveText(/^(<1s|\d+s) · waited \d+s$/);
});

test("a run that waited 1 h and worked 2 min reads 2m 00s · waited 1h 00m", async ({ page }) => {
  const run = {
    id: "00000000-0000-4000-8000-0000000011a2",
    workspace_id: "00000000-0000-0000-0000-000000000001",
    status: "completed",
    workflow: { id: "generate-docs", name: "Waited an hour" },
    template_id: null,
    repo: null,
    created_at: "2026-10-27T09:00:00Z",
    started_at: "2026-10-27T09:00:00Z",
    finished_at: "2026-10-27T10:02:00Z",
    duration_ms: 3_720_000,
    active_ms: 120_000,
    waiting_ms: 3_600_000,
    measured_at: "2026-10-27T10:02:00Z",
    pr_url: null,
    waiting_gate: null,
    cancel_reason: null,
    expired: false,
    rerun_of: null,
    trigger: "api",
    branch: null,
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      estimated_usd: 0,
      cost_complete: true,
      budget_usd: null,
    },
  };
  await page.route(
    // Only the API's /runs: the page itself is also at /runs.
    (url) => url.origin === new URL(apiURL).origin && url.pathname === "/runs",
    (route) => route.fulfill({ json: { items: [run], next_cursor: null } }),
  );

  await page.goto("/runs");
  const all = page.getByRole("table", { name: "All runs" });
  await expect(row(all, run.id).getByTestId("run-time")).toHaveText("2m 00s · waited 1h 00m");
});
