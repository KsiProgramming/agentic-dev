import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, getWorkflow, workflowFromTemplate } from "./workflows";

/** Roadmap 5.2: editing on the canvas round-trips to the stored spec. 5.3: the palette is drawn
 * from the engine's node manifests (`GET /node-types`). */

const agent = (id: string) => ({ type: "agent", id, role: id, instructions: `Do ${id}.` });

function cards(page: Page) {
  return page.getByTestId("builder-node");
}

async function stepMenu(page: Page, nodeId: string, item: string) {
  await page.getByRole("button", { name: `Edit step ${nodeId}` }).click();
  await page.getByRole("menuitem", { name: item, exact: true }).click();
}

/** Adds a `kind` step after `nodeId` from the palette ("Add a step after" submenu). */
async function addAfter(page: Page, nodeId: string, kind: string) {
  await page.getByRole("button", { name: `Edit step ${nodeId}` }).click();
  await page.getByRole("menuitem", { name: "Add a step after" }).click();
  await page.locator(`[role="menuitem"][data-kind="${kind}"]`).click();
}

test("edits on the canvas are saved as a new version and read back", async ({ page, request }) => {
  const id = `e2e-builder-${Date.now()}`;
  const spec = {
    spec_version: "0",
    id,
    name: "E2E builder",
    root: { type: "sequence", id: "main", steps: [agent("draft"), agent("review"), agent("ship")] },
  };
  await createWorkflow(request, spec);

  await page.goto(`/workflows/${id}`);
  await expect(page.getByRole("heading", { level: 1, name: "E2E builder" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(id);
  await expect(cards(page)).toHaveCount(3);

  await addAfter(page, "draft", "agent");
  await stepMenu(page, "agent_1", "Move down");
  await stepMenu(page, "ship", "Remove");
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove" }).click();
  await page.getByRole("button", { name: "Edit details" }).click();
  // The workflow's own fields are in the side panel (5.4): a pane, or a sheet below 1024 px.
  await page.getByLabel("Name").fill("E2E builder, edited");
  await page.keyboard.press("Escape");

  const order = ["draft", "review", "agent_1"];
  expect(
    await cards(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-node"))),
  ).toEqual(order);
  await expect(page.getByTestId("builder-status")).toContainText("4 unsaved changes");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "E2E builder, edited" })).toBeVisible();
  expect(
    await cards(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-node"))),
  ).toEqual(order);

  const latest = await getWorkflow(request, id);
  expect(latest.version).toBe(2);
  expect(latest.base_version).toBe(1);
  expect(latest.spec.name).toBe("E2E builder, edited");
  expect(latest.spec.root.steps.map((s) => s.id)).toEqual(order);
  expect(latest.ops).toHaveLength(4);
  expect((await getWorkflow(request, id, 1)).spec).toEqual(spec);
});

test("the palette lists the engine's node types and adds containers whole", async ({
  page,
  request,
}) => {
  const id = `e2e-palette-${Date.now()}`;
  await createWorkflow(request, {
    spec_version: "0",
    id,
    name: "E2E palette",
    root: { type: "sequence", id: "main", steps: [agent("start")] },
  });
  await page.goto(`/workflows/${id}`);

  await page.getByRole("button", { name: "Edit step start" }).click();
  await page.getByRole("menuitem", { name: "Add a step after" }).click();
  const groups = page.getByRole("group");
  await expect(groups).toHaveCount(3);
  await expect(groups.nth(0)).toContainText("Steps");
  await expect(groups.nth(1)).toContainText("Flow");
  await expect(groups.nth(2)).toContainText("Combine");
  await expect(page.locator('[role="menuitem"][data-kind]')).toHaveCount(9);
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  await addAfter(page, "start", "parallel");
  await addAfter(page, "parallel_1", "reduce");
  await expect(page.getByTestId("builder-node").filter({ hasText: "reduce_1" })).toContainText(
    "Concat of parallel_1",
  );
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");

  const latest = await getWorkflow(request, id);
  const [, parallel, reduce] = latest.spec.root.steps as unknown as Record<string, unknown>[];
  expect(parallel).toMatchObject({
    type: "parallel",
    id: "parallel_1",
    join: "all",
    branches: [{ id: "agent_1" }, { id: "agent_2" }],
  });
  expect(reduce).toMatchObject({ type: "reduce", id: "reduce_1", from: "parallel_1" });
});

test("a step's menu works from the keyboard", async ({ page, request }) => {
  const id = `e2e-builder-keys-${Date.now()}`;
  await createWorkflow(request, {
    spec_version: "0",
    id,
    name: "E2E keys",
    root: { type: "sequence", id: "main", steps: [agent("one"), agent("two")] },
  });
  await page.goto(`/workflows/${id}`);

  await page.getByRole("button", { name: "Edit step two" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toBeVisible();
  await page.getByRole("menuitem", { name: "Move up" }).focus();
  await page.keyboard.press("Enter");

  expect(
    await cards(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-node"))),
  ).toEqual(["two", "one"]);
});

test("Edit in builder opens a template's workflow", async ({ page, request }) => {
  const id = await workflowFromTemplate(request, "generate-docs");
  await page.goto("/templates");
  await page
    .getByTestId("template-card")
    .filter({ hasText: "Generate docs" })
    .getByRole("button", { name: /Edit in builder/ })
    .click();

  await expect(page).toHaveURL(new RegExp(`/workflows/${id}$`));
  await expect(cards(page).first()).toBeVisible();
});
