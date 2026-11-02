import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, requested, stubApi, type Routes } from "@/testing/api";
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

const navigation = vi.hoisted(() => ({
  search: new URLSearchParams(),
  replace: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => navigation.search,
  useRouter: () => ({ replace: navigation.replace, push: navigation.push }),
}));

beforeEach(() => {
  navigation.search = new URLSearchParams();
  navigation.replace.mockReset();
  navigation.push.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  Object.values(toast).forEach((f) => f.mockReset());
});

const PATH = `/workflows/flow?workspace_id=${DEFAULT_WORKSPACE_ID}`;
const VERSIONS = `GET /workflows/flow/versions?workspace_id=${DEFAULT_WORKSPACE_ID}`;
const versionPath = (n: number) => `GET ${PATH}&version=${n}`;
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
    restored_from: n === 3 ? 1 : null,
    valid: true,
    issues: [],
  };
}

/** A row of the history, as `GET /workflows/{id}/versions` answers it. */
function item(n: number, extra: object = {}) {
  return {
    version: n,
    base_version: n > 1 ? n - 1 : null,
    created_at: "2026-11-02T10:00:00Z",
    op_count: n > 1 ? 2 : 0,
    restored_from: null,
    ...extra,
  };
}

function show(routes: Routes) {
  const fetch = stubApi({
    [`GET ${PATH}`]: () => json(200, version(1)),
    "GET /node-types": () => json(200, NODE_TYPES),
    [VERSIONS]: () => json(200, { items: [item(1)] }),
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

test("draws the stored workflow, with an edit menu on every node, nested ones too", async () => {
  show({});

  await screen.findByRole("heading", { name: "Flow" });
  expect(cards()).toEqual(["a", "l", "inner", "c"]);
  expect(screen.getByRole("button", { name: "Edit step inner" })).toBeDefined();
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

/** Opens `nodeId`'s submenu `name` and waits for it. */
async function openSub(nodeId: string, name: string) {
  menu(nodeId);
  fireEvent.keyDown(screen.getByRole("menuitem", { name }), { key: "ArrowRight" });
  return waitFor(() => {
    const menus = screen.getAllByRole("menu");
    expect(menus).toHaveLength(2);
    return within(menus[1]);
  });
}

/** Picks the item of an open submenu that `match`es, and waits for the menus to close. */
async function pick(sub: ReturnType<typeof within>, match: (item: HTMLElement) => boolean) {
  const item = sub.getAllByRole("menuitem").find(match);
  expect(item).toBeDefined();
  fireEvent.click(item!);
  await waitFor(() => expect(screen.queryAllByRole("menu")).toHaveLength(0));
}

async function closeMenu() {
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  await waitFor(() => expect(screen.queryAllByRole("menu")).toHaveLength(0));
}

test("a step added after a loop's body joins it in a new sequence, saved as one batch", async () => {
  const fetch = show({
    [`PATCH ${PATH}`]: async (request) => {
      const body = (await request.clone().json()) as { ops: GraphOp[] };
      return json(201, version(2, applyOps(SPEC, body.ops)));
    },
  });
  await screen.findByRole("heading", { name: "Flow" });

  await add("inner", "gate");
  expect(cards()).toEqual(["a", "l", "inner", "gate_1", "c"]);
  expect(screen.getByTestId("builder-status").textContent).toContain("1 unsaved change");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));

  const { ops } = await waitFor(() => patched(fetch));
  expect(ops).toEqual([
    { op: "addNode", node: { type: "gate", id: "gate_1", title: "Approve" } },
    { op: "connect", from: "inner", to: "gate_1", sequence_id: "sequence_1" },
  ]);
});

test("a lone body cannot be removed or moved away, and says why; it can be replaced", async () => {
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  menu("inner");
  const remove = screen.getByRole("menuitem", { name: /^Remove/ });
  expect(remove.getAttribute("aria-disabled")).toBe("true");
  expect(remove.textContent).toContain("A loop needs a body; replace it instead.");
  await closeMenu();

  await pick(await openSub("inner", "Replace with…"), (i) => i.dataset.kind === "tool");
  const dialog = within(screen.getByRole("alertdialog"));
  expect(dialog.getByText(/A new tool takes its place/)).toBeDefined();
  fireEvent.click(dialog.getByRole("button", { name: "Replace" }));

  expect(cards()).toEqual(["a", "l", "tool_1", "c"]);
  fireEvent.click(screen.getByRole("button", { name: "Undo: Replace inner with tool_1" }));
  expect(cards()).toEqual(["a", "l", "inner", "c"]);
});

test("a step moves into a container and back out, from Move to…", async () => {
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  await pick(await openSub("a", "Move to…"), (i) => i.textContent === "After inner");
  expect(cards()).toEqual(["l", "inner", "a", "c"]);

  await pick(await openSub("a", "Move to…"), (i) => i.textContent === "After c");
  expect(cards()).toEqual(["l", "inner", "c", "a"]);
  expect(screen.getByTestId("builder-status").textContent).toContain("2 unsaved changes");
});

test("a parallel gets a branch, and loses one only while two are left", async () => {
  const parallel = {
    ...SPEC,
    root: {
      type: "sequence",
      id: "main",
      steps: [{ type: "parallel", id: "p", join: "all", branches: [agent("b1"), agent("b2")] }],
    },
  };
  stubApi({
    [`GET ${PATH}`]: () => json(200, version(1, parallel)),
    "GET /node-types": () => json(200, NODE_TYPES),
  });
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);
  await screen.findByRole("heading", { name: "Flow" });

  menu("b1");
  expect(screen.getByRole("menuitem", { name: /^Remove/ }).textContent).toContain(
    "A parallel needs at least two branches.",
  );
  await closeMenu();

  await pick(await openSub("p", "Add a branch"), (i) => i.dataset.kind === "agent");
  expect(cards()).toEqual(["p", "b1", "b2", "agent_1"]);

  menu("b1");
  fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }));
  expect(cards()).toEqual(["p", "b2", "agent_1"]);
});

// 5.6: `a` gives `a`, `b` gives `b`, and `c` needs `b`; `c` cannot follow `a`.
const typed = (id: string, ports: object) => ({ ...agent(id), ...ports });
const TYPED = {
  ...SPEC,
  root: {
    type: "sequence",
    id: "main",
    steps: [
      typed("a", { output_schema: { type: "object", properties: { a: { type: "string" } } } }),
      typed("b", { output_schema: { type: "object", properties: { b: { type: "string" } } } }),
      typed("c", {
        input_schema: { type: "object", properties: { b: { type: "string" } }, required: ["b"] },
      }),
    ],
  },
};
const VALIDATE = "POST /workflows/flow/validate";
const C_NEEDS_B =
  "The input_schema of 'c' requires 'b', which the output_schema of 'a' does not declare.";

function disabledItem(name: string) {
  const item = screen
    .getAllByRole("menuitem")
    .find((i) => i.textContent?.startsWith(name) && i.hasAttribute("data-disabled"));
  expect(item, `${name} disabled`).toBeDefined();
  return item!;
}

test("an edit that would connect ports that do not fit is not offered, and says why", async () => {
  show({ [`GET ${PATH}`]: () => json(200, version(1, TYPED)) });
  await screen.findByRole("heading", { name: "Flow" });

  menu("b");
  expect(disabledItem("Remove").textContent).toContain(C_NEEDS_B);
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

  menu("c");
  expect(disabledItem("Move up").textContent).toContain(C_NEEDS_B);
  fireEvent.keyDown(screen.getByRole("menuitem", { name: "Move to…" }), { key: "ArrowRight" });
  await waitFor(() => expect(screen.getAllByRole("menu")).toHaveLength(2));
  expect(disabledItem("After a").textContent).toContain(C_NEEDS_B);
  fireEvent.keyDown(screen.getAllByRole("menu")[0], { key: "Escape" });
  await waitFor(() => expect(screen.queryAllByRole("menu")).toHaveLength(0));

  // Replacing `b` with an untyped agent breaks the edge instead: allowed.
  menu("b");
  fireEvent.keyDown(screen.getByRole("menuitem", { name: "Replace with…" }), { key: "ArrowRight" });
  const palette = await waitFor(() => {
    const menus = screen.getAllByRole("menu");
    expect(menus).toHaveLength(2);
    return within(menus[1]);
  });
  const item = (kind: string) =>
    palette.getAllByRole("menuitem").find((i) => i.dataset.kind === kind)!;
  expect(item("agent").hasAttribute("data-disabled")).toBe(false);
  expect(cards()).toEqual(["a", "b", "c"]);
});

test("live issues show on their node's card, in the count and in the list", async () => {
  const fetch = show({
    [VALIDATE]: () =>
      json(200, {
        valid: false,
        issues: [
          {
            code: "port_mismatch",
            path: "root.steps[1]",
            node_id: "c",
            message: "agent 'c' at root.steps[1]: input_schema requires 'x'",
          },
          { code: "policy_limit", path: "root", node_id: null, message: "Too many agents." },
        ],
        policy: {},
      }),
  });
  await screen.findByRole("heading", { name: "Flow" });
  expect(requested(fetch)).not.toContain(VALIDATE);

  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));

  const status = screen.getByTestId("builder-status");
  await waitFor(() => expect(status.textContent).toContain("2 issues"));
  expect(requested(fetch).filter((r) => r === VALIDATE)).toHaveLength(1);
  const card = screen.getAllByTestId("builder-node").find((c) => c.dataset.node === "c")!;
  expect(within(card).getByTestId("node-issue").textContent).toContain("input_schema requires 'x'");
  const body = (await fetch.mock.calls
    .find(([r]) => r.method === "POST")![0]
    .clone()
    .json()) as {
    workflow: { root: { steps: { id: string }[] } };
  };
  expect(body.workflow.root.steps.map((s) => s.id)).toEqual(["a", "c", "l"]);

  fireEvent.click(within(status).getByRole("button", { name: /2 issues/ }));
  const list = within(screen.getByTestId("issue-list"));
  expect(list.getByText("Too many agents.")).toBeDefined();
  fireEvent.click(list.getByRole("button", { name: "c" }));
  await waitFor(() => expect(screen.getByTestId("node-panel").dataset.node).toBe("c"));
  expect(
    within(screen.getByTestId("node-panel")).getByRole("list", { name: "Issues" }),
  ).toBeDefined();
});

test("a check that fails says so, with Retry, and blocks nothing", async () => {
  let fail = true;
  show({
    [VALIDATE]: () =>
      fail ? json(500, { detail: "boom" }) : json(200, { valid: true, issues: [], policy: {} }),
  });
  await screen.findByRole("heading", { name: "Flow" });

  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));

  const status = screen.getByTestId("builder-status");
  await waitFor(() => expect(status.textContent).toContain("Could not check the workflow."));
  expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", false);
  fail = false;
  fireEvent.click(within(status).getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(status.textContent).toContain("Ready to run"));
});

test("quick edits are checked once, after the last", async () => {
  const fetch = show({ [VALIDATE]: () => json(200, { valid: true, issues: [], policy: {} }) });
  await screen.findByRole("heading", { name: "Flow" });

  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));
  menu("a");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move down" }));
  expect(screen.getByTestId("builder-status").textContent).toContain("Checking…");

  await waitFor(() =>
    expect(screen.getByTestId("builder-status").textContent).not.toContain("Checking…"),
  );
  expect(requested(fetch).filter((r) => r === VALIDATE)).toHaveLength(1);
  const body = (await fetch.mock.calls
    .find(([r]) => r.method === "POST")![0]
    .clone()
    .json()) as {
    workflow: { root: { steps: { id: string }[] } };
  };
  expect(body.workflow.root.steps.map((s) => s.id)).toEqual(["c", "a", "l"]);
});

/** The spec at version 2: `a` reworded, `c` gone, `d` added. */
const SPEC_2 = {
  ...SPEC,
  root: {
    ...SPEC.root,
    steps: [{ ...agent("a"), instructions: "Plan it." }, SPEC.root.steps[1], agent("d")],
  },
};

const HISTORY = {
  [`GET ${PATH}`]: () => json(200, version(2, SPEC_2)),
  [versionPath(1)]: () => json(200, version(1)),
  [VERSIONS]: () => json(200, { items: [item(2), item(1)] }),
};

test("the history lists every version, and opens one", async () => {
  show({
    [`GET ${PATH}`]: () => json(200, version(3)),
    [VERSIONS]: () =>
      json(200, { items: [item(3, { restored_from: 1, op_count: 0 }), item(2), item(1)] }),
  });
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "History" }));

  const list = within(await screen.findByTestId("version-list"));
  const links = list.getAllByRole("link");
  expect(links.map((l) => l.getAttribute("href"))).toEqual([
    "/workflows/flow",
    "/workflows/flow?version=2",
    "/workflows/flow?version=1",
  ]);
  expect(links[0].textContent).toContain("Latest");
  expect(links[0].textContent).toContain("Restored from version 1");
  expect(links[0].getAttribute("aria-current")).toBe("page");
  expect(links[1].textContent).toContain("2 changes");
  expect(links[2].textContent).toContain("Created");
});

test("leaving unsaved edits for another version asks first", async () => {
  show(HISTORY);
  await screen.findByRole("heading", { name: "Flow" });
  menu("d");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));

  fireEvent.click(screen.getByRole("button", { name: "History" }));
  fireEvent.click(within(await screen.findByTestId("version-list")).getAllByRole("link")[1]);

  const dialog = within(await screen.findByRole("alertdialog"));
  expect(dialog.getByText("Leave unsaved changes?")).toBeDefined();
  expect(navigation.push).not.toHaveBeenCalled();
  fireEvent.click(dialog.getByRole("button", { name: "Leave" }));
  expect(navigation.push).toHaveBeenCalledWith("/workflows/flow?version=1");
});

test("an older version is read-only, with Restore, Run and Back to latest", async () => {
  navigation.search = new URLSearchParams({ version: "1" });
  show(HISTORY);

  await screen.findByRole("heading", { name: "Flow" });
  expect(cards()).toEqual(["a", "l", "inner", "c"]);
  expect(screen.getByTestId("builder-status").textContent).toContain("Version 1 of 2 · read-only");
  expect(screen.queryByRole("button", { name: "Edit step a" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(screen.getByRole("link", { name: "Back to latest" }).getAttribute("href")).toBe(
    "/workflows/flow",
  );
  expect(screen.getByRole("button", { name: "Run this version" })).toHaveProperty(
    "disabled",
    false,
  );
  fireEvent.click(screen.getByRole("button", { name: "Show parameters of a" }));
  const panel = await screen.findByTestId("node-panel");
  expect(within(panel).getByLabelText("Instructions")).toHaveProperty("readOnly", true);
});

test("restoring an older version makes it the latest and opens it", async () => {
  navigation.search = new URLSearchParams({ version: "1" });
  const fetch = show({
    ...HISTORY,
    [`POST /workflows/flow/restore?workspace_id=${DEFAULT_WORKSPACE_ID}`]: () =>
      json(201, version(3)),
  });
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "Restore this version" }));
  const dialog = within(await screen.findByRole("alertdialog"));
  expect(dialog.getByText("Restore version 1?")).toBeDefined();
  expect(dialog.getByText(/It becomes version 3/).textContent).toContain("Version 2 is kept.");
  fireEvent.click(dialog.getByRole("button", { name: "Restore" }));

  await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/workflows/flow"));
  expect(toast.success).toHaveBeenCalledWith("Restored version 1 as version 3.");
  const post = fetch.mock.calls.find(([r]) => r.url.includes("/restore"))![0];
  expect(await post.clone().json()).toEqual({ base_version: 2, version: 1 });
});

test("a restore refused for a newer version says so in its dialog", async () => {
  navigation.search = new URLSearchParams({ version: "1" });
  show({
    ...HISTORY,
    [`POST /workflows/flow/restore?workspace_id=${DEFAULT_WORKSPACE_ID}`]: () =>
      json(409, {
        detail: { code: "version_conflict", message: "stale", latest_version: 3 },
      }),
  });
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "Restore this version" }));
  const dialog = within(await screen.findByRole("alertdialog"));
  fireEvent.click(dialog.getByRole("button", { name: "Restore" }));

  expect((await dialog.findByRole("alert")).textContent).toContain(
    "Someone saved a newer version meanwhile.",
  );
  expect(navigation.push).not.toHaveBeenCalled();
});

test("comparing marks changed and added cards, and lists what was removed", async () => {
  navigation.search = new URLSearchParams({ compare: "1" });
  show(HISTORY);
  await screen.findByRole("heading", { name: "Flow" });

  const mark = (id: string) =>
    within(screen.getAllByTestId("builder-node").find((c) => c.dataset.node === id)!).queryByTestId(
      "diff-badge",
    )?.textContent;
  await waitFor(() => expect(mark("a")).toBe("Changed"));
  expect(mark("d")).toBe("Added");
  expect(mark("l")).toBeUndefined();
  expect(screen.getByLabelText("Compare with")).toHaveProperty("value", "1");

  const summary = screen.getByTestId("diff-summary");
  expect(summary.textContent).toContain("1 added · 1 changed · 1 removed");
  fireEvent.click(summary);
  const list = within(await screen.findByTestId("change-list"));
  expect(list.getByRole("list", { name: "Removed steps" }).textContent).toContain("c");
  fireEvent.click(list.getByRole("button", { name: "a" }));

  const changes = within(await screen.findByTestId("panel-changes"));
  expect(changes.getByText("instructions")).toBeDefined();
  expect(changes.getByText("Do a.")).toBeDefined();
  expect(changes.getByText("Plan it.")).toBeDefined();

  fireEvent.change(screen.getByLabelText("Compare with"), { target: { value: "" } });
  expect(navigation.replace).toHaveBeenCalledWith("/workflows/flow");
});

test("Run waits for unsaved edits to be saved and issues to be fixed", async () => {
  show({
    [`GET ${PATH}`]: () =>
      json(200, {
        ...version(1),
        valid: false,
        issues: [{ code: "policy_limit", path: "root", node_id: null, message: "Too many." }],
      }),
  });
  await screen.findByRole("heading", { name: "Flow" });
  const run = screen.getByRole("button", { name: "Run" });
  expect(run).toHaveProperty("disabled", true);
  expect(document.getElementById(run.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Fix the issue first.",
  );
});

test("Run opens the run sheet for the version shown, and waits for a save", async () => {
  show({
    [`GET /workspaces/${DEFAULT_WORKSPACE_ID}/connections`]: () => json(200, []),
    [VALIDATE]: () => json(200, { valid: true, issues: [], policy: {} }),
  });
  await screen.findByRole("heading", { name: "Flow" });

  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  const sheet = within(await screen.findByTestId("workflow-run-sheet"));
  expect(sheet.getByRole("heading", { name: "New run: Flow" })).toBeDefined();
  fireEvent.click(sheet.getByRole("button", { name: "Cancel" }));

  menu("c");
  fireEvent.click(screen.getByRole("menuitem", { name: "Move up" }));
  const run = screen.getByRole("button", { name: "Run" });
  expect(run).toHaveProperty("disabled", true);
  expect(document.getElementById(run.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Save your changes first.",
  );
});

test("?node= opens with that node selected (a new blank workflow's starter agent)", async () => {
  navigation.search = new URLSearchParams({ node: "a" });
  show({});
  await screen.findByRole("heading", { name: "Flow" });

  expect(
    screen.getByRole("button", { name: "Edit parameters of a" }).getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    screen.getByRole("button", { name: "Edit parameters of inner" }).getAttribute("aria-pressed"),
  ).toBe("false");
});
