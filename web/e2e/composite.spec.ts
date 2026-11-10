import { expect, test, type Page } from "@playwright/test";

import { endedRunEvents } from "./runs";
import { createWorkflow, getWorkflow } from "./workflows";
import { apiURL, e2eWorkspaceId } from "./workspace";

/** Roadmap 6.6, AC-3: a composite saved in one workflow is reused in another and updated by
 * version. Steps of workflow A are extracted to a composite and published; workflow B adds it
 * from the palette and runs it; a newer published version reaches B only by B's own edit. */

const agent = (id: string) => ({ type: "agent", id, role: id, instructions: `Do ${id}.` });

const workflow = (id: string, name: string, ...steps: object[]) => ({
  spec_version: "0",
  id,
  name,
  root: { type: "sequence", id: "main", steps },
});

const card = (page: Page, nodeId: string) =>
  page.locator(`[data-testid="builder-node"][data-node="${nodeId}"]`).filter({ visible: true });

async function publish(page: Page, version: number) {
  await page.getByRole("button", { name: `Publish version ${version}` }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Publish" }).click();
  await expect(page.getByTestId("published-badge").filter({ visible: true })).toBeVisible();
}

async function run(page: Page, workflowId: string, version: number): Promise<string> {
  const started = await page.request.post(`${apiURL}/runs`, {
    data: {
      stored_workflow: { id: workflowId, version },
      input: "hello",
      workspace_id: e2eWorkspaceId(),
    },
  });
  expect(started.status(), await started.text()).toBe(202);
  const runId = ((await started.json()) as { run_id: string }).run_id;
  const events = await endedRunEvents(page.request, runId);
  expect(events.at(-1)?.type).toBe("run_completed");
  return runId;
}

test("a composite extracted from one workflow is reused in another and updated by version", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const source = `e2e-source-${stamp}`;
  const caller = `e2e-caller-${stamp}`;
  const composite = `e2e-review-${stamp}`;
  await createWorkflow(
    request,
    workflow(source, "E2E source", agent("plan"), agent("check"), agent("verdict")),
  );
  await createWorkflow(request, workflow(caller, "E2E caller", agent("draft")));

  // 1. Extract two steps of the source into a composite, and save.
  await page.goto(`/workflows/${source}`);
  await page.getByRole("button", { name: "Edit step check" }).click();
  await page.getByRole("menuitem", { name: "Extract to composite…" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Steps").selectOption("verdict");
  await dialog.getByLabel("Name").fill(`E2E review ${stamp}`);
  await dialog.getByLabel("Id").fill(composite);
  await dialog.getByRole("button", { name: "Extract" }).click();
  await expect(card(page, "subflow_1")).toContainText("stored when you save");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");
  const extracted = await getWorkflow(request, composite);
  expect(extracted.spec.root.steps.map((s) => s.id)).toEqual(["check", "verdict"]);

  // 2. Publish its version 1.
  await page.goto(`/workflows/${composite}`);
  await publish(page, 1);

  // 3. Add it to the caller from the palette, save and run: its steps run inside the call.
  await page.goto(`/workflows/${caller}`);
  await page.getByRole("button", { name: "Edit step draft" }).click();
  await page.getByRole("menuitem", { name: "Add a step after" }).click();
  await page.locator(`[role="menuitem"][data-composite="${composite}"]`).click();
  await expect(card(page, "subflow_1")).toContainText(`Calls E2E review ${stamp} · version 1`);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");
  const first = await run(page, caller, 2);
  await page.goto(`/runs/${first}`);
  await expect(page.locator('[data-testid="step-row"][data-key="subflow_1/check"]')).toBeVisible();

  // 4. A newer published version is offered to the caller, never applied on its own.
  await page.goto(`/workflows/${composite}`);
  await page.getByRole("button", { name: "Edit step verdict" }).click();
  await page.getByRole("menuitem", { name: "Edit parameters" }).click();
  await page.getByLabel("Role").fill("judge");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Draft · version 1 is published");
  await publish(page, 2);
  expect((await getWorkflow(request, caller)).spec.root.steps[1]).toMatchObject({
    workflow: { id: composite, version: 1 },
  });

  // 5. Update the caller to version 2, save, and run it again.
  await page.goto(`/workflows/${caller}`);
  await expect(card(page, "subflow_1")).toContainText("version 2 is published");
  await page.getByRole("button", { name: "Edit step subflow_1" }).click();
  await page.getByRole("menuitem", { name: "Update to version 2" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 3");
  const second = await run(page, caller, 3);
  await page.goto(`/runs/${second}`);
  await expect(page.locator('[data-testid="step-row"][data-key="subflow_1"]')).toContainText(
    "version 2",
  );
});
