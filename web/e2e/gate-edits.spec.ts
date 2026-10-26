import { expect, test, type Page } from "@playwright/test";

import { endedRunEvents, startReviewRun } from "./runs";

/** Roadmap 3.6: a gate is approved from the UI with edits, and the pull request carries them. */

/** The modified side of the review sheet's diff, ready to type in. */
async function modifiedEditor(page: Page) {
  const review = page.getByTestId("gate-review");
  const editor = review.locator(
    ".monaco-diff-editor .editor.modified .view-lines:not(.line-delete)",
  );
  await expect(editor).toBeVisible({ timeout: 30_000 });
  return editor;
}

test("a gate is approved with edits, and the pull request carries them", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const runId = await startReviewRun(request);
  await page.goto(`/runs/${runId}`);
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 60_000 });

  // The writer's file is listed and shown as a diff.
  await dock.getByRole("button", { name: "Review details" }).click();
  const review = page.getByTestId("gate-review");
  const files = review.getByRole("navigation", { name: "Changed files" });
  await expect(files.getByRole("button", { name: /NOTES\.md/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  const editor = await modifiedEditor(page);
  await expect(editor).toContainText("Written by an agent.");

  // Edit it: the approval now carries one edit.
  await editor.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("\nReviewed at the gate.");
  await expect(review.getByText("1 file edited")).toBeVisible();
  await expect(files.getByText("Edited")).toBeVisible();
  await review.getByRole("button", { name: "Approve with 1 edit" }).click();

  // The run goes on and opens the pull request; its step says the gate took edits.
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    { timeout: 60_000 },
  );
  await expect(page.getByTestId("gate-decision")).toHaveText("· Approved with edits to 1 file");
  await page.getByRole("button", { name: "View edits" }).click();
  await expect(await modifiedEditor(page)).toContainText("Reviewed at the gate.");

  // The branch the pull request pushed is the gate's edit commit, on top of the writer's.
  const events = await endedRunEvents(request, runId);
  const decided = events.find((e) => e.type === "gate_decided")!;
  expect(decided.payload.edits).toEqual([
    {
      node_id: "writer",
      path: "NOTES.md",
      content: expect.stringContaining("Reviewed at the gate."),
    },
  ]);
  const tip = (decided.payload.commits as Record<string, string>).writer!;
  const opened = events.find((e) => e.type === "pr_opened")!;
  expect(tip.startsWith(String(opened.payload.commit))).toBe(true);
});

test("discarding the edits leaves a plain approval", async ({ page, request }) => {
  test.setTimeout(120_000);
  const runId = await startReviewRun(request);
  await page.goto(`/runs/${runId}`);
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 60_000 });
  await dock.getByRole("button", { name: "Review details" }).click();
  const review = page.getByTestId("gate-review");
  const editor = await modifiedEditor(page);

  await editor.click();
  await page.keyboard.type("Scratch ");
  await review.getByRole("button", { name: "Discard edits" }).click();
  await expect(review.getByText("Edit a file to change it before approving.")).toBeVisible();

  // Escape closes the sheet; the dock approves with no edits.
  await page.keyboard.press("Escape");
  await expect(review).toBeHidden();
  await dock.getByRole("button", { name: /^Approve/ }).click();
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    { timeout: 60_000 },
  );
  const decided = (await endedRunEvents(request, runId)).find((e) => e.type === "gate_decided")!;
  expect(decided.payload).not.toHaveProperty("edits");
});
