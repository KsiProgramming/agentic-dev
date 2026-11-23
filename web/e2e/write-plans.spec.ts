import { expect, test } from "@playwright/test";

import { apiURL, endedRunEvents, startReviewRun, withPlans } from "./runs";

/** Done when (13.8): a gate shows what approving does, and the event log shows the plan and the
 * result side by side. The stack's fake GitHub App plans the pull request. */
test("the Inbox shows the plan of the pull request, and approving checks it", async ({
  page,
  request,
}) => {
  const name = `Plans ${Date.now().toString(36)}`;
  const runId = await startReviewRun(request, name);

  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await expect(review.getByRole("heading", { name: "What approving does" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(review.getByText("Approving lets the run go on")).toHaveCount(0);
  const card = review.getByTestId("write-plan");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("open a pull request");
  await expect(card).toContainText("e2e-org/docs-demo");
  await expect(card).toContainText("Add notes");

  await review.getByRole("button", { name: /^Approve/ }).click();

  const events = await endedRunEvents(request, runId);
  const planned = events.find((e) => e.type === "writes_planned");
  const checked = events.find((e) => e.type === "write_checked");
  expect(planned?.node_id).toBe("approve");
  expect(checked?.node_id).toBe("publish");
  expect(checked?.payload).toMatchObject({
    gate: "approve",
    outcome: "as_planned",
    differences: [],
  });
  expect(checked?.payload.plan).toBeTruthy();
  expect(checked?.payload.result).toBeTruthy();

  await page.goto(`/runs/${runId}?step=publish`);
  await expect(page.getByTestId("write-checked")).toHaveText("As planned at approve", {
    timeout: 30_000,
  });
});

test("a plan that would fail is shown, and Approve stays on", async ({ page, request }) => {
  const runId = await startReviewRun(request, `Would fail ${Date.now().toString(36)}`);
  await withPlans(page);

  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  const cards = review.getByTestId("write-plan");
  await expect(cards).toHaveCount(3, { timeout: 30_000 });
  await expect(cards.nth(1)).toContainText("The export is in the pull request.");
  await expect(cards.nth(1).getByTestId("plan-pending")).toContainText("added once it is open");
  await expect(cards.nth(2).getByText("Would fail")).toBeVisible();
  await expect(cards.nth(2).getByTestId("plan-error")).toContainText("transition_unavailable");
  await expect(review.getByRole("button", { name: /^Approve/ })).toBeEnabled();
  await request.post(`${apiURL}/runs/${runId}/cancel`);
});
