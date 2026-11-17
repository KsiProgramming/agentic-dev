import { expect, test } from "@playwright/test";

import {
  clearJiraTriggers,
  connectGithub,
  connectJira,
  DOCS_DEMO,
  JIRA_PROJECT,
  JIRA_SITE,
} from "./connections";
import { apiURL } from "./runs";
import { ensureWorkspace, storageState } from "./workspace";

// Settings › Triggers (7.3) on the fake Atlassian: add a rule from the sheet, see it listed with
// its site listening, turn it off and on, and delete it after confirming. It works in a
// workspace of its own, since it clears the rules the a11y and layout specs read, and its tests
// run one after another.
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ request, context, baseURL }) => {
  const workspaceId = await ensureWorkspace(request, "E2E Jira");
  await connectGithub(request, workspaceId);
  await connectJira(request, workspaceId);
  await clearJiraTriggers(request, workspaceId);
  await context.addCookies(storageState(workspaceId, baseURL!).cookies);
});

test("a trigger is added, paused and deleted from Settings › Triggers", async ({ page }) => {
  await page.goto("/settings/triggers");
  const card = page.getByTestId("jira-triggers-card");
  await expect(card.getByText("No trigger yet.")).toBeVisible();

  await card.getByRole("button", { name: "New trigger" }).click();
  const sheet = page.getByTestId("jira-trigger-sheet");
  await expect(sheet.getByRole("heading", { name: "New trigger" })).toBeVisible();
  await expect(sheet.getByLabel("Project")).toHaveValue("API");
  await sheet.getByLabel("Status").selectOption("In Progress");
  await sheet.getByLabel("Run").selectOption({ label: "Answer a Jira issue" });
  await sheet.getByRole("combobox", { name: "Repository" }).click();
  await page.getByRole("option", { name: new RegExp(DOCS_DEMO) }).click();
  await sheet.getByRole("button", { name: "Add trigger" }).click();
  await expect(sheet).toBeHidden();

  const row = card.getByTestId("jira-trigger").filter({ visible: true });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("When an issue in API moves to In Progress");
  await expect(row).toContainText("Answer a Jira issue");
  await expect(row).toContainText("Not fired yet");
  await expect(card.getByTestId("jira-listening")).toContainText("Listening");

  const name = "the trigger: API moves to In Progress";
  await row.getByRole("button", { name: `Turn off ${name}` }).click();
  await expect(row).toHaveAttribute("data-enabled", "false");
  await expect(row).toContainText("Off");
  await row.getByRole("button", { name: `Turn on ${name}` }).click();
  await expect(row).toHaveAttribute("data-enabled", "true");

  await row.getByRole("button", { name: `Delete ${name}` }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(card.getByText("No trigger yet.")).toBeVisible();
});

test("the sheet checks its fields before saving", async ({ page }) => {
  await page.goto("/settings/triggers");
  await page.getByRole("button", { name: "New trigger" }).click();
  const sheet = page.getByTestId("jira-trigger-sheet");
  await sheet.getByLabel("When an issue").selectOption("label");
  await sheet.getByLabel("Label").fill("two words");
  await sheet.getByRole("button", { name: "Add trigger" }).click();

  await expect(sheet.getByText("A Jira label has no spaces.")).toBeVisible();
  await expect(sheet.getByText("Pick what runs.")).toBeVisible();
  await expect(sheet.getByLabel("Label")).toHaveAttribute("aria-invalid", "true");
});

test("a project's fields are mapped from the Jira card (7.4)", async ({ page, request }) => {
  const workspaceId = await ensureWorkspace(request, "E2E Jira");
  const cleared = await request.put(
    `${apiURL}/workspaces/${workspaceId}/jira/sites/${JIRA_SITE}/projects/${JIRA_PROJECT.key}/fields`,
    { data: { acceptance_criteria: null, story_points: null } },
  );
  expect(cleared.status(), await cleared.text()).toBe(200);

  await page.goto("/settings/integrations");
  const card = page.getByTestId("jira-card");
  const projects = card.getByRole("list", { name: "Projects of Acme" });
  await expect(projects).toContainText("No fields mapped");
  await card.getByRole("button", { name: "Map fields of Acme" }).click();

  const sheet = page.getByTestId("jira-fields-sheet");
  await expect(sheet.getByRole("heading", { name: "Fields of Acme" })).toBeVisible();
  await sheet
    .getByLabel("Acceptance criteria")
    .selectOption({ label: "Acceptance criteria · Paragraph · suggested" });
  await sheet
    .getByLabel("Story points")
    .selectOption({ label: "Story point estimate · Number · suggested" });
  await sheet.getByRole("button", { name: "Save fields" }).click();
  await expect(sheet).toBeHidden();
  await expect(projects).toContainText("Fields mapped");
  await expect(projects).not.toContainText("No fields mapped");
});
