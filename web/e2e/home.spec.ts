import { expect, test } from "@playwright/test";

test("home redirects to runs without console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  await page.goto("/");

  await expect(page).toHaveURL(/\/runs$/);
  await expect(page.getByTestId("app-shell")).toBeVisible();
  await expect(page.getByTestId("workspace-name")).toBeVisible();
  await expect(page).toHaveTitle("Runs · Agentic Dev");
  expect(errors).toEqual([]);
});
