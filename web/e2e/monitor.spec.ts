import { expect, test, type Page } from "@playwright/test";

import { apiURL } from "./runs";

/** Fail the test on any console error, CORS errors included. */
function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}

interface Row {
  seq: number;
  type: string;
  createdAt: number;
  receivedAt: number;
}

async function rows(page: Page): Promise<Row[]> {
  return page.getByTestId("event-row").evaluateAll((els) =>
    els.map((el) => {
      const d = (el as HTMLElement).dataset;
      return {
        seq: Number(d.seq),
        type: d.type ?? "",
        createdAt: Date.parse(d.createdAt ?? ""),
        receivedAt: Number(d.receivedAt),
      };
    }),
  );
}

async function expectCompletedRun(page: Page): Promise<Row[]> {
  await expect(page.getByTestId("run-status")).toHaveAttribute("data-status", "succeeded", {
    timeout: 30_000,
  });
  const listed = await rows(page);
  expect(listed.map((r) => r.seq)).toEqual(listed.map((_, i) => i + 1));
  expect(listed[0]?.type).toBe("run_started");
  expect(listed.at(-1)?.type).toBe("run_completed");
  return listed;
}

test("a run started from the templates page shows its events within 1 s", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/templates");

  await page.getByLabel("Input").fill("hello from e2e");
  await page.getByRole("button", { name: "Start sample run" }).click();

  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
  const listed = await expectCompletedRun(page);

  // Events written before the page connected arrive as a replay; every event written after
  // that is live and must show up within 1 s of being stored.
  const connectedAt = listed[0]!.receivedAt;
  const live = listed.filter((r) => r.createdAt >= connectedAt);
  expect(live.length).toBeGreaterThanOrEqual(3);
  for (const row of live) {
    expect(row.receivedAt - row.createdAt, `${row.type} #${row.seq}`).toBeLessThan(1000);
  }
  expect(errors).toEqual([]);
});

test("a run started with POST /runs can be opened by its id", async ({ page, request }) => {
  const errors = watchConsole(page);
  const response = await request.post(`${apiURL}/runs`, {
    data: {
      workflow: {
        spec_version: "0",
        id: "e2e",
        name: "E2E",
        root: { type: "agent", id: "writer", role: "Writer", instructions: "Say hello." },
      },
      input: "hello",
    },
  });
  expect(response.status()).toBe(202);
  const { run_id } = (await response.json()) as { run_id: string };

  await page.goto(`/runs/${run_id}`);

  await expectCompletedRun(page);
  expect(errors).toEqual([]);
});

test("an unknown run says it was not found", async ({ page }) => {
  await page.goto("/runs/00000000-0000-0000-0000-000000000000");

  await expect(page.getByText("Run not found.")).toBeVisible();
});
