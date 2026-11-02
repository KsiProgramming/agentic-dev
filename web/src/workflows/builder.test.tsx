import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { json, renderWithQueries, stubApi, type Routes } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import type { WorkflowVersion } from "./api";
import { applyOps, type GraphOp } from "./ops";
import { WorkflowBuilder } from "./builder";

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
  const fetch = stubApi({ [`GET ${PATH}`]: () => json(200, version(1)), ...routes });
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);
  return fetch;
}

const cards = () => screen.getAllByTestId("builder-node").map((c) => c.dataset.node);

function menu(nodeId: string) {
  fireEvent.keyDown(screen.getByRole("button", { name: `Edit step ${nodeId}` }), { key: "Enter" });
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

  menu("a");
  fireEvent.click(screen.getByRole("menuitem", { name: "Agent" }));
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
    [`PATCH ${PATH}`]: () =>
      json(409, { detail: { code: "version_conflict", message: "stale", latest_version: 2 } }),
  };
  stubApi(routes);
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);
  await screen.findByRole("heading", { name: "Flow" });
  menu("a");
  fireEvent.click(screen.getByRole("menuitem", { name: "Gate" }));

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

test("an unknown workflow says so and leads to the templates", async () => {
  stubApi({ [`GET ${PATH}`]: () => json(404, { detail: "workflow flow not found" }) });
  renderWithQueries(<WorkflowBuilder workflowId="flow" />);

  expect(await screen.findByText("There is no workflow with this id.")).toBeDefined();
  expect(screen.getByRole("link", { name: "Go to templates" }).getAttribute("href")).toBe(
    "/templates",
  );
});
