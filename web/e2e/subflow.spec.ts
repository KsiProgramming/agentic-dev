import { expect, test, type Page } from "@playwright/test";

import { endedRunEvents } from "./runs";
import { createWorkflow, getWorkflow } from "./workflows";
import { apiURL, e2eWorkspaceId } from "./workspace";

/** Roadmap 6.5: one workflow calls another by id + version. The call is made on the canvas with
 * the side panel's picker, and the run's console nests the called workflow's steps under it. */

const agent = (id: string) => ({ type: "agent", id, role: id, instructions: `Do ${id}.` });

const workflow = (id: string, name: string, ...steps: object[]) => ({
  spec_version: "0",
  id,
  name,
  root: { type: "sequence", id: "main", steps },
});

async function addAfter(page: Page, nodeId: string, kind: string) {
  await page.getByRole("button", { name: `Edit step ${nodeId}` }).click();
  await page.getByRole("menuitem", { name: "Add a step after" }).click();
  await page.locator(`[role="menuitem"][data-kind="${kind}"]`).click();
}

test("a workflow calls another, picked on the canvas, and its run nests the call", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const child = `e2e-child-${stamp}`;
  const parent = `e2e-parent-${stamp}`;
  // Both roots are `main`: the called one runs renamed, and the console still nests it.
  await createWorkflow(request, workflow(child, "E2E child", agent("check"), agent("verdict")));
  await createWorkflow(request, workflow(parent, "E2E parent", agent("draft")));

  await page.goto(`/workflows/${parent}`);
  await addAfter(page, "draft", "subflow");
  await page.getByRole("button", { name: "Edit step subflow_1" }).click();
  await page.getByRole("menuitem", { name: "Edit parameters" }).click();
  await page.getByLabel("Workflow").selectOption(child);
  await expect(page.getByLabel("Version")).toHaveValue("1");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("builder-status")).toContainText("Ready to run");
  await expect(page.locator('[data-node="subflow_1"]')).toContainText(
    "Calls E2E child · version 1",
  );
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");

  const saved = await getWorkflow(request, parent);
  expect(saved.spec.root.steps.map((s) => s.id)).toEqual(["draft", "subflow_1"]);
  expect(saved.spec.root.steps[1]).toMatchObject({ workflow: { id: child, version: 1 } });

  const started = await request.post(`${apiURL}/runs`, {
    data: {
      stored_workflow: { id: parent, version: 2 },
      input: "hello",
      workspace_id: e2eWorkspaceId(),
    },
  });
  expect(started.status(), await started.text()).toBe(202);
  const runId = ((await started.json()) as { run_id: string }).run_id;
  const events = await endedRunEvents(request, runId);
  expect(events.at(-1)?.type).toBe("run_completed");

  await page.goto(`/runs/${runId}`);
  const rows = page.getByTestId("step-row");
  await expect(rows).toHaveCount(4);
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-key")))).toEqual([
    "draft",
    "subflow_1",
    "subflow_1/check",
    "subflow_1/verdict",
  ]);
  await expect(page.locator('[data-testid="step-row"][data-key="subflow_1"]')).toContainText(
    "Called E2E child · version 1",
  );

  await page.goto(`/runs/${runId}?view=graph`);
  const nodes = page.getByTestId("map-node");
  await expect(nodes).toHaveCount(4);
  expect(await nodes.evaluateAll((els) => els.map((e) => e.getAttribute("data-node")))).toEqual([
    "draft",
    "subflow_1",
    "check",
    "verdict",
  ]);
});
