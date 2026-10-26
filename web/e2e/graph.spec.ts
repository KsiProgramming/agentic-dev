import { expect, test, type Page } from "@playwright/test";

import { apiURL, COMBINE, GATE, MAP, startRun } from "./runs";

/** Roadmap 3.5: clicking a node in the graph shows what the agent did. */

function graphNode(page: Page, nodeId: string) {
  return page.locator(`[data-testid="graph-node"][data-node-id="${nodeId}"]`);
}

/** A run of a map, a reduce and a gate, opened on its Graph tab once it waits at the gate. */
async function openWaitingGraph(page: Page, request: Parameters<typeof startRun>[0]) {
  const runId = await startRun(request, [MAP, COMBINE, GATE], "E2E graph");
  await page.goto(`/runs/${runId}?tab=graph`);
  await expect(page.getByTestId("approval-dock").filter({ visible: true })).toBeVisible({
    timeout: 30_000,
  });
  await expect(graphNode(page, "approve")).toHaveAttribute("data-status", "waiting");
  return runId;
}

test("clicking a node in the graph shows what the agent did", async ({ page, request }) => {
  const runId = await openWaitingGraph(page, request);

  // Every node of the spec is drawn, with its status in words.
  await expect(page.getByTestId("graph-node")).toHaveCount(4);
  await expect(graphNode(page, "each")).toHaveAccessibleName("each, map, Done, 2 of 2 items");
  await expect(graphNode(page, "approve")).toHaveAccessibleName("approve, gate, Needs approval");

  await graphNode(page, "worker").click();
  const sheet = page.getByTestId("node-detail");
  await expect(sheet.getByRole("heading", { name: "worker" })).toBeVisible();
  const items = sheet.getByTestId("map-item");
  await expect(items).toHaveCount(2);
  await expect(items.first().getByRole("heading", { level: 4 })).toHaveText("alpha");
  await expect(sheet.getByTestId("agent-message").first()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
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
  const sheet = page.getByTestId("node-detail");
  await expect(sheet.getByTestId("map-item")).toHaveCount(2);

  // The dock's shortcuts are off while the sheet is open.
  await page.keyboard.press("a");
  await expect(page.getByTestId("approval-dock").filter({ visible: true })).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
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
