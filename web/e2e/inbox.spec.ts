import { expect, test, type Page } from "@playwright/test";

import { endedRunEvents, GATE, startRun, WRITER } from "./runs";

/** Every URL the page navigated to, to show the run console was never opened. */
function visited(page: Page): string[] {
  const urls: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) urls.push(frame.url());
  });
  return urls;
}

/** Done when (11.5): a gate is approved from the Inbox without opening the run console. */
test("a gate is approved from the Inbox without opening its run", async ({ page, request }) => {
  const name = `Inbox ${Date.now().toString(36)}`;
  const runId = await startRun(request, [WRITER, GATE], name);
  const urls = visited(page);

  await page.goto("/inbox");
  const entry = page
    .getByRole("navigation", { name: "Waiting gates" })
    .getByRole("link")
    .filter({ hasText: name });
  await expect(entry).toBeVisible({ timeout: 30_000 });
  await expect(entry).toContainText(GATE.title);
  await expect(entry).toContainText(/Expires in/);
  await entry.click();
  await expect(page).toHaveURL(new RegExp(`run=${runId}`));

  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await expect(review.getByRole("heading", { name: GATE.title })).toBeVisible();
  await expect(review.getByText("Approving lets the run go on")).toBeVisible();
  await review.getByRole("button", { name: /^Approve/ }).click();
  await expect(page.getByText(`Approved: ${GATE.title}`)).toBeVisible();
  await expect(entry).toHaveCount(0);

  const events = await endedRunEvents(request, runId);
  expect(events.find((e) => e.type === "gate_decided")).toMatchObject({
    payload: { decision: "approve" },
  });
  expect(events.at(-1)?.type).toBe("run_completed");
  expect(urls.some((url) => new URL(url).pathname.startsWith("/runs/"))).toBe(false);
});

test("A approves the gate the Inbox shows", async ({ page, request }) => {
  const runId = await startRun(request, [WRITER, GATE], `Inbox key ${Date.now().toString(36)}`);

  await page.goto(`/inbox?run=${runId}`);
  const review = page.getByTestId("inbox-review").filter({ visible: true });
  await expect(review.getByRole("heading", { name: GATE.title })).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press("a");
  await expect(page.getByText(`Approved: ${GATE.title}`)).toBeVisible();

  const events = await endedRunEvents(request, runId);
  expect(events.at(-1)?.type).toBe("run_completed");
});
