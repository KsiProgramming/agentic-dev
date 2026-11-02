import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, stubApi, type Routes } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import type { WorkflowVersion } from "./api";
import { applyOps, type GraphOp } from "./ops";
import { WorkflowBuilder } from "./builder";
import type { NodeManifest } from "./node-types";

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  apiBaseUrl: () => "http://api.test",
}));

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

afterEach(() => {
  vi.unstubAllGlobals();
  Object.values(toast).forEach((f) => f.mockReset());
});

const PATH = `/workflows/flow?workspace_id=${DEFAULT_WORKSPACE_ID}`;
// The engine's manifests, as `GET /node-types` answers them (`scripts/export_workflow_schema.py`).
const NODE_TYPES = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/node-types.json"), "utf8"),
) as NodeManifest[];
// A primitive this app has never heard of: the palette and the cards still show it (5.3).
const ECHO: NodeManifest = {
  kind: "echo",
  label: "Echo",
  description: "Says its text back.",
  category: "step",
  icon: "megaphone",
  parameters: { type: "object", properties: { text: { type: "string" } } },
  slots: [],
  default: { type: "echo", id: "echo", text: "hello" },
  fill: {},
};
const agent = (id: string) => ({ type: "agent", id, role: id, instructions: `Do ${id}.` });

const SPEC = {
  spec_version: "0",
  id: "flow",
  name: "Flow",
  root: {
    type: "sequence",
    id: "main",
    steps: [
      agent("a"),
      { type: "loop", id: "l", body: agent("inner"), until: "true", max_iterations: 2 },
      agent("c"),
    ],
  },
};

function version(n: number, spec: object = SPEC): WorkflowVersion {
  return {
    workflow_id: "flow",
    version: n,
    base_version: n > 1 ? n - 1 : null,
    created_at: "2026-11-02T10:00:00Z",
    spec: spec as WorkflowVersion["spec"],
    ops: null,
    valid: true,
    issues: [],
  };
}

function show(routes: Routes) {
  const fetch = stubApi({
    [`GET ${PATH}`]: () => json(200, version(1)),
    "GET /node-types": () => json(200, NODE_TYPES),
    ...routes,
  });
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);
  return fetch;
}

const cards = () => screen.getAllByTestId("builder-node").map((c) => c.dataset.node);

function menu(nodeId: string) {
  fireEvent.keyDown(screen.getByRole("button", { name: `Edit step ${nodeId}` }), { key: "Enter" });
}

/** Opens `nodeId`'s "Add a step after" palette and waits for it. */
async function openPalette(nodeId: string) {
  menu(nodeId);
  const trigger = screen.getByRole("menuitem", { name: "Add a step after" });
  fireEvent.keyDown(trigger, { key: "ArrowRight" });
  return waitFor(() => {
    const menus = screen.getAllByRole("menu");
    expect(menus).toHaveLength(2);
    return within(menus[1]);
  });
}

/** Picks `kind` in `nodeId`'s palette. */
async function add(nodeId: string, kind: string) {
  const palette = await openPalette(nodeId);
  const item = palette.getAllByRole("menuitem").find((i) => i.dataset.kind === kind);
  expect(item).toBeDefined();
  fireEvent.click(item!);
  await waitFor(() => expect(screen.queryAllByRole("menu")).toHaveLength(0));
}

async function patched(fetch: ReturnType<typeof stubApi>) {
  const call = fetch.mock.calls.find(([r]) => r.method === "PATCH");
  return (await call![0].clone().json()) as { base_version: number; ops: GraphOp[] };
}

test("draws the stored workflow, and only root steps get an edit menu", async () => {
  show({});

  await screen.findByRole("heading", { name: "Flow" });
  expect(cards()).toEqual(["a", "l", "inner", "c"]);
  expect(screen.queryByRole("button", { name: "Edit step inner" })).toBeNull();
  expect(screen.getByTestId("builder-status").textContent).toContain("Version 1");
  expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
});

test("edits are drawn at once and saved as one PATCH of their ops", async () => {
  const fetch = show({
    [`PATCH ${PATH}`]: async (request) => {
      const body = (await request.clone().json()) as { ops: GraphOp[] };
      return json(201, version(2, applyOps(SPEC, body.ops)));
    },
  });
  await screen.findByRole("heading", { name: "Flow" });

  await add("a", "agent");
  menu("a");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move down" }));
  expect(cards()).toEqual(["agent_1", "a", "l", "inner", "c"]);
  expect(screen.getByTestId("builder-status").textContent).toContain("2 unsaved changes");

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(screen.getByTestId("builder-status").textContent).toContain("Version 2"),
  );
  expect(await patched(fetch)).toEqual({
    base_version: 1,
    ops: [
      {
        op: "addNode",
        node: {
          type: "agent",
          id: "agent_1",
          role: "Agent",
          instructions: "Describe what this agent does.",
          tools: [],
          reads: [],
        },
        at: { after: "a" },
      },
      { op: "connect", from: "agent_1", to: "a" },
    ],
  });
  expect(cards()).toEqual(["agent_1", "a", "l", "inner", "c"]);
  expect(screen.getByTestId("builder-status").textContent).not.toContain("unsaved");
  expect(toast.success).toHaveBeenCalledWith("Saved version 2");
});

test("undo takes back the last edit", async () => {
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));
  expect(cards()).toEqual(["a", "c", "l", "inner"]);
  fireEvent.click(screen.getByRole("button", { name: "Undo: Move c up" }));

  expect(cards()).toEqual(["a", "l", "inner", "c"]);
});

test("removing a step asks first and names what goes with it", async () => {
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  menu("l");
  fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));
  const dialog = within(screen.getByRole("alertdialog"));
  expect(dialog.getByText(/The 1 node under it go too/)).toBeDefined();
  fireEvent.click(dialog.getByRole("button", { name: "Remove" }));

  expect(cards()).toEqual(["a", "c"]);
});

test("after a conflict the edits are applied to the latest version and kept", async () => {
  const routes: Routes = {
    [`GET ${PATH}`]: () => json(200, version(1)),
    "GET /node-types": () => json(200, NODE_TYPES),
    [`PATCH ${PATH}`]: () =>
      json(409, { detail: { code: "version_conflict", message: "stale", latest_version: 2 } }),
  };
  stubApi(routes);
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);
  await screen.findByRole("heading", { name: "Flow" });
  await add("a", "gate");

  routes[`GET ${PATH}`] = () => json(200, version(2, { ...SPEC, name: "Renamed elsewhere" }));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await screen.findByRole("heading", { name: "Renamed elsewhere" });
  expect(cards()).toEqual(["a", "gate_1", "l", "inner", "c"]);
  expect(screen.getByTestId("builder-status").textContent).toContain("Version 2");
  expect(screen.getByTestId("builder-status").textContent).toContain("1 unsaved change");
  expect(toast.info).toHaveBeenCalledWith(
    "Updated to version 2; your edits were kept. Save again.",
  );
});

test("a refused batch is shown on the card it names", async () => {
  show({
    [`PATCH ${PATH}`]: () =>
      json(422, {
        detail: { code: "schema", message: "agent 'a' needs a role", op_index: null, node_id: "a" },
      }),
  });
  await screen.findByRole("heading", { name: "Flow" });
  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));

  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  const card = await waitFor(() => {
    const found = screen.getAllByTestId("builder-node").find((c) => c.dataset.node === "a");
    expect(found?.textContent).toContain("agent 'a' needs a role");
    return found!;
  });
  expect(card).toBeDefined();
  expect(toast.error).toHaveBeenCalledWith("agent 'a' needs a role");
});

test("the palette lists the engine's node types by category, a new one included", async () => {
  show({ "GET /node-types": () => json(200, [...NODE_TYPES, ECHO]) });
  await screen.findByRole("heading", { name: "Flow" });

  await add("a", "echo");

  expect(cards()).toEqual(["a", "echo_1", "l", "inner", "c"]);
  const card = screen.getAllByTestId("builder-node").find((c) => c.dataset.node === "echo_1");
  expect(card?.textContent).toContain("Echo");

  const groups = (await openPalette("c")).getAllByRole("group");
  expect(groups.map((g) => g.textContent?.split(/(?=[A-Z])/)[0])).toEqual([
    "Steps",
    "Flow",
    "Combine",
  ]);
  expect(within(groups[0]).getByRole("menuitem", { name: /^Echo/ })).toBeDefined();
});

test("a container comes with its children, every one under a fresh id", async () => {
  const fetch = show({
    [`PATCH ${PATH}`]: async (request) => {
      const body = (await request.clone().json()) as { ops: GraphOp[] };
      return json(201, version(2, applyOps(SPEC, body.ops)));
    },
  });
  await screen.findByRole("heading", { name: "Flow" });

  await add("c", "parallel");
  await add("parallel_1", "reduce");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  const { ops } = await waitFor(() => patched(fetch));
  expect(ops[0]).toMatchObject({
    node: { type: "parallel", id: "parallel_1", branches: [{ id: "agent_1" }, { id: "agent_2" }] },
  });
  expect(ops[1]).toMatchObject({ node: { type: "reduce", id: "reduce_1", from: "parallel_1" } });
});

test("the palette says when the node types cannot load, and retries", async () => {
  const routes: Routes = {
    [`GET ${PATH}`]: () => json(200, version(1)),
    "GET /node-types": () => json(500, { detail: "down" }),
  };
  stubApi(routes);
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);
  await screen.findByRole("heading", { name: "Flow" });
  const failed = await openPalette("a");
  await waitFor(() => expect(failed.getByRole("menuitem", { name: "Retry" })).toBeDefined());
  expect(failed.getByText("down")).toBeDefined();

  routes["GET /node-types"] = () => json(200, []);
  fireEvent.click(failed.getByRole("menuitem", { name: "Retry" }));
  await waitFor(() => expect(screen.queryAllByRole("menu")).toHaveLength(0));
  const empty = await openPalette("a");
  await waitFor(() => expect(empty.getByText("No node types available")).toBeDefined());
});

test("an unknown workflow says so and leads to the templates", async () => {
  stubApi({ [`GET ${PATH}`]: () => json(404, { detail: "workflow flow not found" }) });
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);

  expect(await screen.findByText("There is no workflow with this id.")).toBeDefined();
  expect(screen.getByRole("link", { name: "Go to templates" }).getAttribute("href")).toBe(
    "/templates",
  );
});

/** Below 1024 px (and in jsdom) the panel is a sheet over the page: close it. */
async function closeSheet() {
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}

test("a nested agent's instructions are edited in the panel, typed as one undo step, and saved", async () => {
  const fetch = show({
    [`PATCH ${PATH}`]: async (request) => {
      const body = (await request.clone().json()) as { ops: GraphOp[] };
      return json(201, version(2, applyOps(SPEC, body.ops)));
    },
  });
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "Edit parameters of inner" }));
  const panel = await screen.findByTestId("node-panel");
  expect(panel.dataset.node).toBe("inner");
  const instructions = within(panel).getByLabelText("Instructions");
  fireEvent.change(instructions, { target: { value: "Do" } });
  fireEvent.change(instructions, { target: { value: "Do it well." } });
  expect(screen.getByTestId("builder-status").textContent).toContain("1 unsaved change");

  await closeSheet();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(screen.getByTestId("builder-status").textContent).toContain("Version 2"),
  );
  expect(await patched(fetch)).toEqual({
    base_version: 1,
    ops: [{ op: "setParam", node_id: "inner", path: "instructions", value: "Do it well." }],
  });
});

test("undo brings a parameter back in the panel", async () => {
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  menu("a");
  fireEvent.click(screen.getByRole("menuitem", { name: "Edit parameters" }));
  const panel = await screen.findByTestId("node-panel");
  fireEvent.change(within(panel).getByLabelText("Role"), { target: { value: "Editor" } });
  expect(screen.getByTestId("builder-status").textContent).toContain("1 unsaved change");

  await closeSheet();
  fireEvent.click(screen.getByRole("button", { name: /^Undo/ }));
  fireEvent.click(screen.getByRole("button", { name: "Edit parameters of a" }));
  const again = await screen.findByTestId("node-panel");
  expect((within(again).getByLabelText("Role") as HTMLInputElement).value).toBe("a");
});

test("the workflow's budget is set from Edit details, and sent without a node", async () => {
  const fetch = show({
    [`PATCH ${PATH}`]: async (request) => {
      const body = (await request.clone().json()) as { ops: GraphOp[] };
      return json(201, version(2, applyOps(SPEC, body.ops)));
    },
  });
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "Edit details" }));
  const panel = await screen.findByTestId("workflow-panel");
  fireEvent.change(within(panel).getByLabelText(/^Budget/), { target: { value: "2" } });
  await closeSheet();
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(screen.getByTestId("builder-status").textContent).toContain("Version 2"),
  );
  expect(await patched(fetch)).toEqual({
    base_version: 1,
    ops: [{ op: "setParam", path: "budget_usd", value: 2 }],
  });
});

test("Escape and Close close the panel; with nothing selected it shows the workflow", async () => {
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "Edit parameters of c" }));
  await screen.findByTestId("node-panel");
  fireEvent.keyDown(screen.getByRole("button", { name: "Close" }), { key: "Escape" });
  await waitFor(() => expect(screen.queryByTestId("node-panel")).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Edit parameters of c" }));
  await screen.findByTestId("node-panel");
  await closeSheet();
  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));
  const dialog = within(await screen.findByRole("alertdialog"));
  fireEvent.click(dialog.getByRole("button", { name: "Remove" }));
  expect(cards()).toEqual(["a", "l", "inner"]);
  fireEvent.click(screen.getByRole("button", { name: "Edit details" }));
  expect(await screen.findByTestId("workflow-panel")).toBeTruthy();
});
