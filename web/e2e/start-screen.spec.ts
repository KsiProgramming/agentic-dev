import { expect, test } from "@playwright/test";

import { getWorkflow } from "./workflows";

/** Roadmap 5.8: a user starts a canvas workflow without touching JSON. */

test("a blank canvas becomes a saved workflow without any JSON", async ({ page, request }) => {
  const name = `E2E blank ${Date.now()}`;
  const id = name.toLowerCase().replaceAll(" ", "-");

  await page.goto("/templates");
  const blank = page.getByTestId("blank-canvas-card");
  await expect(blank).toBeVisible();
  await blank.getByRole("button", { name: /blank workflow/ }).click();

  const sheet = page.getByTestId("new-workflow-sheet");
  await sheet.getByLabel("Name").fill(name);
  await expect(sheet.getByLabel("Id")).toHaveValue(id);
  await expect(sheet.getByRole("radio", { name: /Claude/ })).toBeChecked();
  await expect(sheet.getByRole("radio", { name: /GitHub Copilot/ })).toBeDisabled();
  await sheet.getByRole("button", { name: "Create workflow" }).click();

  await expect(page).toHaveURL(new RegExp(`/workflows/${id}\\?node=agent_1$`));
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByTestId("builder-status")).toContainText("Version 1");

  // The starter agent's parameters, in the side panel (a sheet below 1024 px).
  await page.getByRole("button", { name: "Edit parameters of agent_1" }).click();
  const panel = page.getByTestId("node-panel");
  await panel.getByLabel("Role").fill("Writer");
  await panel.getByLabel("Instructions").fill("Write the release notes.");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Edit step agent_1" }).click();
  await page.getByRole("menuitem", { name: "Add a step after" }).click();
  await page.locator('[role="menuitem"][data-kind="gate"]').click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");

  const latest = await getWorkflow(request, id);
  expect(latest.spec.root.steps.map((s) => s.type)).toEqual(["agent", "gate"]);

  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByTestId("workflow-run-sheet")).toContainText("Claude");
  await page.keyboard.press("Escape");

  await page
    .getByRole("navigation", { name: "Breadcrumb" })
    .getByRole("link", { name: "Workflows" })
    .click();
  await expect(page).toHaveURL(/\/workflows$/);
  await expect(page.getByRole("link", { name }).first()).toBeVisible();
});

test("the command palette opens the new workflow sheet", async ({ page }) => {
  await page.goto("/workflows");
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("dialog").getByRole("combobox").fill("new workflow");
  await page.getByRole("option", { name: "New workflow" }).click();

  await expect(page).toHaveURL(/\/workflows\?blank=1$/);
  await expect(page.getByTestId("new-workflow-sheet")).toBeVisible();
});
