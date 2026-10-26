import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { WORKSPACE_ID } from "./connections";
import { apiURL, endedRunEvents, GATE, startRun, WRITER } from "./runs";

/** Roadmap 3.7: every run and approval is listed per workspace on the audit log. */

async function waitForStatus(request: APIRequestContext, runId: string, status: string) {
  await expect
    .poll(
      async () =>
        (
          (await (await request.get(`${apiURL}/runs/${runId}`)).json()) as {
            status: string;
          }
        ).status,
      { timeout: 30_000 },
    )
    .toBe(status);
}

/** The actions of the audit entries on the page, top to bottom. */
function actions(page: Page) {
  return page.locator("[data-action]").filter({ visible: true });
}

test("a run, its approval, a cancelled rerun and a limits change are all listed", async ({
  page,
  request,
}) => {
  const runId = await startRun(request, [WRITER, GATE], "E2E audit");
  await waitForStatus(request, runId, "waiting");
  const approval = await request.post(`${apiURL}/runs/${runId}/approvals`, {
    data: { node_id: "approve", decision: "approve", comment: "e2e looks good" },
  });
  expect(approval.status()).toBe(202);
  await endedRunEvents(request, runId);

  const rerun = await request.post(`${apiURL}/runs/${runId}/rerun`);
  expect(rerun.status()).toBe(202);
  const rerunId = ((await rerun.json()) as { run_id: string }).run_id;
  await waitForStatus(request, rerunId, "waiting");
  expect((await request.post(`${apiURL}/runs/${rerunId}/cancel`)).status()).toBe(202);
  await endedRunEvents(request, rerunId);

  // Saving the platform's own limit changes the workspace's settings, not what runs may do.
  const policyURL = `${apiURL}/workspaces/${WORKSPACE_ID}/policy`;
  const before = ((await (await request.get(policyURL)).json()) as { overrides: object }).overrides;
  expect((await request.put(policyURL, { data: { ...before, agents_alive: 8 } })).status()).toBe(
    200,
  );
  expect((await request.put(policyURL, { data: before })).status()).toBe(200);

  await page.goto(`/audit?run=${runId}`);
  await expect(page.getByRole("heading", { level: 1, name: "Audit log" })).toBeVisible();
  await expect(actions(page)).toHaveCount(3);
  expect(await actions(page).evaluateAll((els) => els.map((e) => e.dataset.action))).toEqual([
    "run.ended",
    "gate.approved",
    "run.created",
  ]);
  await expect(actions(page).nth(1)).toContainText("Approved approve");
  await expect(actions(page).nth(1)).toContainText("e2e looks good");
  await expect(actions(page).nth(0)).toContainText("System");

  await page.goto(`/audit?run=${rerunId}`);
  await expect(actions(page)).toHaveCount(3);
  expect(await actions(page).evaluateAll((els) => els.map((e) => e.dataset.action))).toEqual([
    "run.ended",
    "run.cancel_requested",
    "run.rerun",
  ]);
  await expect(actions(page).nth(2)).toContainText(`Rerun of ${runId.slice(0, 8)}`);

  await page.goto("/audit?category=settings");
  await expect(actions(page).first()).toHaveAttribute("data-action", "policy.updated");
  await expect(actions(page).nth(1)).toContainText("agents alive default → 8");

  // A run's id opens its console.
  await page.goto(`/audit?run=${runId}`);
  await actions(page)
    .last()
    .getByRole("link", { name: `Run ${runId.slice(0, 8)}` })
    .click();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
});

test("Audit log is in the main navigation", async ({ page }) => {
  await page.goto("/runs");
  await page
    .getByRole("complementary", { name: "Sidebar" })
    .getByRole("link", { name: "Audit log" })
    .click();
  await expect(page).toHaveURL(/\/audit$/);
  await expect(page.getByRole("heading", { level: 1, name: "Audit log" })).toBeVisible();
});
