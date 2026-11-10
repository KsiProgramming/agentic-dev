import { expect, test, type Locator, type Page } from "@playwright/test";

import { endedRunEvents } from "./runs";
import { getWorkflow } from "./workflows";

/** Roadmap 6.8, AC-2: a user builds a flow with a parallel, an orchestrator, a loop and a gate on
 * the canvas, by menu items only, and the run matches the drawn graph: the run map draws the
 * same cards joined by the same edges as the canvas of the version that ran, every card with
 * the status its events give. The stack's fake agents fit a typed node's schema (6.8), so the
 * hub plans one task and the reviewer approves the first pass. */

test.use({ viewport: { width: 1440, height: 900 } });

const VERDICT = {
  type: "object",
  required: ["verdict", "feedback"],
  properties: {
    verdict: { type: "string", enum: ["ok", "changes"] },
    feedback: { type: "string" },
  },
};

const builderCards = (page: Page) => page.getByTestId("builder-node").filter({ visible: true });

async function cardIds(page: Page): Promise<string[]> {
  return builderCards(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-node")!));
}

/** The ids of the cards `edit` added to the canvas, in canvas order. */
async function added(page: Page, edit: () => Promise<void>): Promise<string[]> {
  const before = new Set(await cardIds(page));
  await edit();
  await expect.poll(async () => (await cardIds(page)).length).toBeGreaterThan(before.size);
  return (await cardIds(page)).filter((id) => !before.has(id));
}

async function openMenu(page: Page, nodeId: string) {
  await page.getByRole("button", { name: `Edit step ${nodeId}` }).click();
}

/** Adds a `kind` step after `nodeId` from the palette; returns the ids of the cards it added. */
function addAfter(page: Page, nodeId: string, kind: string): Promise<string[]> {
  return added(page, async () => {
    await openMenu(page, nodeId);
    await page.getByRole("menuitem", { name: "Add a step after" }).click();
    await page.locator(`[role="menuitem"][data-kind="${kind}"]:not([data-composite])`).click();
  });
}

/** Wraps `first` through `last` of their sequence in a `kind` container ("Parallel", "Loop"). */
async function wrap(page: Page, first: string, last: string, kind: string): Promise<string> {
  const [container] = await added(page, async () => {
    await openMenu(page, first);
    await page.getByRole("menuitem", { name: "Wrap in…" }).click();
    await page.getByRole("menuitem", { name: `${kind}…` }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Steps").selectOption(last);
    await dialog.getByRole("button", { name: "Wrap" }).click();
  });
  return container!;
}

/** Opens `nodeId`'s side panel, runs `edit` in it and closes it. */
async function inPanel(
  page: Page,
  nodeId: string,
  edit: (panel: ReturnType<Page["getByTestId"]>) => Promise<void>,
) {
  await page.getByRole("button", { name: `Edit parameters of ${nodeId}` }).click();
  const panel = page.getByTestId("node-panel").filter({ visible: true });
  await expect(panel).toContainText(nodeId);
  await edit(panel);
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
}

async function agentParams(
  page: Page,
  nodeId: string,
  role: string,
  instructions: string,
  tools: string[] = [],
) {
  await inPanel(page, nodeId, async (panel) => {
    await panel.getByLabel("Role").fill(role);
    await panel.getByLabel("Instructions").fill(instructions);
    for (const tool of tools) await panel.getByRole("checkbox", { name: tool }).check();
  });
}

/** The graph a view draws: its cards, and its edges other than wraps (a sequence wraps to its
 * pane's width, which differs between the canvas and the run map). */
async function drawnGraph(page: Page, scope: string) {
  const box = page.getByTestId(scope).filter({ visible: true });
  const cards = await box
    .locator("[data-flow-card]")
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-flow-card")));
  const edges = await box
    .locator("g[data-edge]:not([data-edge='wrap'])")
    .evaluateAll((els) =>
      els.map((e) => `${e.getAttribute("data-from")}→${e.getAttribute("data-to")}`).sort(),
    );
  return { cards, edges };
}

test("a flow drawn on the canvas with parallel, orchestrator, loop and gate runs as drawn", async ({
  page,
  request,
}) => {
  test.setTimeout(300_000);
  const name = `E2E AC-2 ${Date.now()}`;
  const id = name.toLowerCase().replaceAll(" ", "-");

  // 1. A blank canvas: its starter agent.
  await page.goto("/templates");
  await page
    .getByTestId("blank-canvas-card")
    .getByRole("button", { name: /blank workflow/ })
    .click();
  const sheet = page.getByTestId("new-workflow-sheet");
  await sheet.getByLabel("Name").fill(name);
  await sheet.getByRole("button", { name: "Create workflow" }).click();
  await expect(page).toHaveURL(new RegExp(`/workflows/${id}\\?node=agent_1$`));
  await page.keyboard.press("Escape");
  const [first] = await cardIds(page);

  // 2. Two analysts in a parallel.
  const [second] = await addAfter(page, first!, "agent");
  const explore = await wrap(page, first!, second!, "Parallel");

  // 3. An orchestrator with its worker, a synthesizer and a reviewer, in a loop.
  const [implement, engineer] = await addAfter(page, explore, "orchestrator");
  const [synthesizer] = await addAfter(page, implement!, "agent");
  const [reviewer] = await addAfter(page, synthesizer!, "agent");
  const loop = await wrap(page, implement!, reviewer!, "Loop");

  // 4. A gate, then the pull request.
  const [gate] = await addAfter(page, loop, "gate");
  const [publish] = await addAfter(page, gate!, "tool");

  // 5. The parameters, in the side panel.
  await agentParams(page, first!, "Code analyst", "Your input is the request. Map the code.", [
    "repo.read_file",
  ]);
  await agentParams(page, second!, "Test analyst", "Your input is the request. Find the tests.", [
    "repo.read_file",
  ]);
  await agentParams(page, engineer!, "Engineer", "Your input is your task. Do it and commit.", [
    "repo.write_file",
    "repo.commit",
  ]);
  await agentParams(page, synthesizer!, "Release writer", "Your input is the engineers' reports.");
  await agentParams(page, reviewer!, "Reviewer", "Your input is the description. Review it.", [
    "repo.read_file",
  ]);
  await inPanel(page, reviewer!, async (panel) => {
    await panel.getByRole("button", { name: "Advanced" }).click();
    await panel.getByLabel("Output schema").fill(JSON.stringify(VERDICT));
  });
  await inPanel(page, loop, async (panel) => {
    await panel.getByLabel("Until").fill(`results.${reviewer}.data.verdict == "ok"`);
  });
  await inPanel(page, publish!, async (panel) => {
    await panel.getByLabel("Tool").selectOption({ label: "github.openPR" });
    await panel
      .getByLabel("Args")
      .fill(JSON.stringify({ from_node: implement, title: "AC-2", body: "Drawn on the canvas." }));
  });

  // 6. It validates, and is saved as version 2.
  const status = page.getByTestId("builder-status");
  await expect(status).toContainText("Ready to run", { timeout: 15_000 });
  await page.getByRole("button", { name: "Save" }).click();
  await expect(status).toContainText("Version 2");
  const saved = (await getWorkflow(request, id)).spec as unknown as {
    root: { steps: { type: string; id: string }[] };
  };
  expect(saved.root.steps.map((s) => s.type)).toEqual(["parallel", "loop", "gate", "tool"]);
  const canvas = await drawnGraph(page, "builder-canvas");
  expect(canvas.cards).toEqual([
    explore,
    first,
    second,
    loop,
    implement,
    engineer,
    synthesizer,
    reviewer,
    gate,
    publish,
  ]);

  // 7. Run this version from the builder, on a repo, with a request.
  await page.getByRole("button", { name: "Run", exact: true }).click();
  const runSheet = page.getByTestId("workflow-run-sheet");
  await runSheet.getByRole("combobox", { name: "Repository" }).click();
  await page.getByRole("option", { name: /docs-demo/ }).click();
  await runSheet.getByLabel("Input").fill("Add a changelog, with a test.");
  await runSheet.getByRole("button", { name: "Start run" }).click();
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+/);
  const runId = new URL(page.url()).pathname.split("/").at(-1)!;

  // 8. It reaches the gate after one pass; approving opens the pull request.
  const dock = page.getByTestId("approval-dock").filter({ visible: true });
  await expect(dock).toBeVisible({ timeout: 180_000 });
  await dock.getByRole("button", { name: /^Approve/ }).click();
  await expect(page.getByTestId("run-status").filter({ visible: true })).toHaveAttribute(
    "data-status",
    "succeeded",
    { timeout: 60_000 },
  );
  const events = await endedRunEvents(request, runId);
  expect(events.some((e) => e.type === "pr_opened" && e.node_id === publish)).toBe(true);

  // 9. The run map draws what was drawn on the canvas, every step completed.
  await page.goto(`/runs/${runId}?view=graph`);
  const map = page.getByTestId("run-map").filter({ visible: true });
  await expect(map).toBeVisible();
  expect(await drawnGraph(page, "run-map")).toEqual(canvas);
  const statuses = await map
    .getByTestId("map-node")
    .evaluateAll((els) =>
      els.map((e) => [e.getAttribute("data-node"), e.getAttribute("data-status")]),
    );
  expect(statuses).toEqual(canvas.cards.map((card) => [card, "completed"]));
  await expect(map.getByTestId("map-task")).toHaveCount(1);
});

/** Presses `key` until `target` has the focus, at most `max` times. */
async function keyTo(page: Page, target: Locator, key: string, max = 40) {
  for (let i = 0; i < max; i++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press(key);
  }
  throw new Error(`${key} never reached ${target.toString()}`);
}

/** Opens `nodeId`'s step menu from the keyboard: its "⋯" button takes the focus, Enter opens it. */
async function menuByKeys(page: Page, nodeId: string) {
  await page.getByRole("button", { name: `Edit step ${nodeId}` }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toBeVisible();
}

/** Adds a `kind` step after `nodeId` with the keyboard only: arrows to "Add a step after",
 * ArrowRight into the palette, arrows to the kind, Enter. */
function addAfterByKeys(page: Page, nodeId: string, kind: string): Promise<string[]> {
  return added(page, async () => {
    await menuByKeys(page, nodeId);
    await keyTo(page, page.getByRole("menuitem", { name: "Add a step after" }), "ArrowDown");
    await page.keyboard.press("ArrowRight");
    const item = page.locator(`[role="menuitem"][data-kind="${kind}"]:not([data-composite])`);
    await keyTo(page, item, "ArrowDown");
    await page.keyboard.press("Enter");
  });
}

/** Wraps `first` through `last` in a `kind` container with the keyboard only. */
async function wrapByKeys(page: Page, first: string, last: string, kind: string): Promise<string> {
  const [container] = await added(page, async () => {
    await menuByKeys(page, first);
    await keyTo(page, page.getByRole("menuitem", { name: "Wrap in…" }), "ArrowDown");
    await page.keyboard.press("ArrowRight");
    await keyTo(page, page.getByRole("menuitem", { name: `${kind}…` }), "ArrowDown");
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    const steps = dialog.getByLabel("Steps");
    await keyTo(page, steps, "Tab");
    for (let i = 0; i < 10 && (await steps.inputValue()) !== last; i++) {
      await page.keyboard.press("ArrowDown");
    }
    await expect(steps).toHaveValue(last);
    await keyTo(page, dialog.getByRole("button", { name: "Wrap" }), "Tab");
    await page.keyboard.press("Enter");
  });
  return container!;
}

test("the same flow's parallel, orchestrator, loop and gate are built with the keyboard only", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const name = `E2E AC-2 keys ${Date.now()}`;
  const id = name.toLowerCase().replaceAll(" ", "-");
  await page.goto("/templates");
  await page
    .getByTestId("blank-canvas-card")
    .getByRole("button", { name: /blank workflow/ })
    .click();
  const sheet = page.getByTestId("new-workflow-sheet");
  await sheet.getByLabel("Name").fill(name);
  await sheet.getByRole("button", { name: "Create workflow" }).click();
  await expect(page).toHaveURL(new RegExp(`/workflows/${id}\?node=agent_1$`));
  await page.keyboard.press("Escape");
  const [first] = await cardIds(page);

  const [second] = await addAfterByKeys(page, first!, "agent");
  const explore = await wrapByKeys(page, first!, second!, "Parallel");
  const [implement] = await addAfterByKeys(page, explore, "orchestrator");
  const [reviewer] = await addAfterByKeys(page, implement!, "agent");
  const loop = await wrapByKeys(page, implement!, reviewer!, "Loop");
  await addAfterByKeys(page, loop, "gate");

  const save = page.getByRole("button", { name: "Save" });
  await save.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("builder-status")).toContainText("Version 2");
  const saved = (await getWorkflow(request, id)).spec as unknown as {
    root: { steps: { type: string; id: string; body?: { steps: { type: string }[] } }[] };
  };
  expect(saved.root.steps.map((s) => s.type)).toEqual(["parallel", "loop", "gate"]);
  expect(saved.root.steps[1]!.body!.steps.map((s) => s.type)).toEqual(["orchestrator", "agent"]);
});
