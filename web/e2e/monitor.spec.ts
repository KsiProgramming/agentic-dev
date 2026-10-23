import { expect, test, type Page } from "@playwright/test";

import { DOCS_DEMO } from "./connections";
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
  /** The last `seq` of the row: chunks of one message are folded into one row. */
  lastSeq: number;
  type: string;
  createdAt: number;
  receivedAt: number;
}

async function rows(page: Page): Promise<Row[]> {
  await page.getByRole("tab", { name: "Raw events" }).click();
  // The panel renders after the click: read the rows once they are there.
  await expect(page.getByTestId("event-row").first()).toBeVisible();
  return page.getByTestId("event-row").evaluateAll((els) =>
    els.map((el) => {
      const d = (el as HTMLElement).dataset;
      return {
        seq: Number(d.seq),
        lastSeq: Number(d.lastSeq),
        type: d.type ?? "",
        createdAt: Date.parse(d.createdAt ?? ""),
        receivedAt: Number(d.receivedAt),
      };
    }),
  );
}

async function expectCompletedRun(page: Page): Promise<Row[]> {
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    {
      timeout: 30_000,
    },
  );
  const listed = await rows(page);
  // Every event is listed once, in order, with no gaps.
  const seqs = listed.flatMap((r) =>
    Array.from({ length: r.lastSeq - r.seq + 1 }, (_, i) => r.seq + i),
  );
  expect(seqs).toEqual(seqs.map((_, i) => i + 1));
  expect(listed[0]?.type).toBe("run_started");
  expect(listed.at(-1)?.type).toBe("run_completed");
  return listed;
}

test("a docs run is started from the template gallery", async ({ page, request }) => {
  const errors = watchConsole(page);
  await page.goto("/templates");

  await page.getByRole("button", { name: "Start Generate docs" }).click();
  const sheet = page.getByTestId("new-run-sheet");
  await sheet.getByRole("combobox", { name: "Repository" }).click();
  await page.getByRole("option", { name: new RegExp(DOCS_DEMO) }).click();
  await sheet.getByRole("button", { name: "Start run" }).click();

  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    /running|waiting/,
    {
      timeout: 30_000,
    },
  );
  expect(errors).toEqual([]);
  // Leave nothing waiting on the runs pages of the other tests.
  const runId = page.url().split("/").at(-1)!;
  await request.post(`${apiURL}/runs/${runId}/cancel`);
});

test("a docs run waits at its gate, is approved from the dock and opens a pull request", async ({
  page,
  request,
}) => {
  const response = await request.post(`${apiURL}/runs`, {
    data: {
      template: { id: "generate-docs", parameters: {} },
      repo: { url: `https://github.com/${DOCS_DEMO}` },
    },
  });
  expect(response.status()).toBe(202);
  const { run_id } = (await response.json()) as { run_id: string };

  // Waiting runs are counted on Runs in the sidebar and in the title of every page.
  await page.goto("/runs");
  await expect(page.getByRole("link", { name: /Review/ }).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(page).toHaveTitle(/^\(\d+\+?\) ● Needs approval · Runs/);

  await page.goto(`/runs/${run_id}`);
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 60_000 });
  await expect(dock.getByRole("heading")).toHaveText(
    "Open a pull request with the generated docs?",
  );
  await dock.getByRole("button", { name: /Approve/ }).click();

  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    {
      timeout: 60_000,
    },
  );
  await expect(
    page.getByRole("link", { name: new RegExp(`${DOCS_DEMO}/pull/\\d+`) }).first(),
  ).toBeVisible();
});

test("a run started with POST /runs shows its events within 1 s", async ({ page, request }) => {
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

  const listed = await expectCompletedRun(page);
  // Events written before the page connected arrive as a replay; every event written after
  // that is live and must show up within 1 s of being stored.
  const connectedAt = listed[0]!.receivedAt;
  const live = listed.filter((r) => r.createdAt >= connectedAt);
  for (const row of live) {
    expect(row.receivedAt - row.createdAt, `${row.type} #${row.seq}`).toBeLessThan(1000);
  }
  expect(errors).toEqual([]);
});

test("an unknown run says it was not found", async ({ page }) => {
  await page.goto("/runs/00000000-0000-0000-0000-000000000000");

  await expect(page.getByText("Run not found.")).toBeVisible();
});
