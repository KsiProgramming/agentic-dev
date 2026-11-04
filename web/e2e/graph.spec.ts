import { expect, test, type Page } from "@playwright/test";

import { apiURL, COMBINE, GATE, MAP, startRun } from "./runs";

/** Roadmap 3.5 and 11.6: clicking a node in the graph shows what the agent did, in the step
 * panel beside it. */

function graphNode(page: Page, nodeId: string) {
  return page.locator(`[data-testid="map-node"][data-node="${nodeId}"]`);
}

/** A run of a map, a reduce and a gate, opened on its Graph tab once it waits at the gate. */
async function openWaitingGraph(page: Page, request: Parameters<typeof startRun>[0]) {
  const runId = await startRun(request, [MAP, COMBINE, GATE], "E2E graph");
  await page.goto(`/runs/${runId}?view=graph`);
  await expect(page.getByTestId("approval-dock").filter({ visible: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(graphNode(page, "approve")).toHaveAttribute("data-status", "waiting");
  return runId;
}

test("clicking a node in the graph shows what the agent did", async ({ page, request }) => {
  const runId = await openWaitingGraph(page, request);

  // Every node of the spec is drawn, named by its visible text with its status and kind in words
  // (the browser may put a space where hidden and visible text meet; speech ignores it).
  await expect(page.getByTestId("map-node")).toHaveCount(4);
  await expect(graphNode(page, "each")).toHaveAccessibleName(/^each ?, Done, 2 of 2 items ?, map$/);
  await expect(graphNode(page, "approve")).toHaveAccessibleName(
    /^approve ?, Needs approval, .+ ?, gate$/,
  );

  await graphNode(page, "worker").click();
  await expect(graphNode(page, "worker")).toHaveAttribute("aria-pressed", "true");
  // The last item's run of the node, its answer in Output.
  const panel = page.getByTestId("step-panel");
  await expect(panel).toHaveAttribute("data-key", "each[1]/worker");
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("beta");
  await expect(panel.getByTestId("agent-message").first()).toBeVisible();
  await expect(page).toHaveURL(/step=each%5B1%5D%2Fworker/);
  await request.post(`${apiURL}/runs/${runId}/cancel`);
});

test("the graph is used with the keyboard only", async ({ page, request }) => {
  await openWaitingGraph(page, request);

  // From the Graph tab, Tab reaches the nodes one by one.
  await page.getByRole("tab", { name: "Graph" }).focus();
  const worker = graphNode(page, "worker");
  for (let i = 0; i < 10 && !(await worker.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(worker).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("step-panel")).toHaveAttribute("data-key", "each[1]/worker");
  await expect(worker).toBeFocused();

  // With focus on the graph, A approves the gate.
  await page.keyboard.press("a");
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    { timeout: 30_000 },
  );
  await expect(graphNode(page, "approve")).toHaveAttribute("data-status", "completed");
});
