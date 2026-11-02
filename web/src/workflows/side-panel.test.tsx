import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { SpecNode, WorkflowSpec } from "@/runs/graph/spec-graph";

import type { Edit } from "./edits";
import type { NodeManifest } from "./node-types";
import { NodePanel, WorkflowPanel } from "./side-panel";

// The engine's manifests, as `GET /node-types` answers them (`scripts/export_workflow_schema.py`).
const NODE_TYPES = JSON.parse(
  readFileSync(resolve(__dirname, "../../../schemas/fixtures/node-types.json"), "utf8"),
) as NodeManifest[];

// A primitive this app has never heard of: its panel comes from its schema alone.
const ECHO: NodeManifest = {
  kind: "echo",
  label: "Echo",
  description: "Says its text back.",
  category: "step",
  icon: "megaphone",
  parameters: {
    type: "object",
    required: ["text"],
    properties: { text: { type: "string", minLength: 1, title: "Text" } },
  },
  slots: [],
  default: { type: "echo", id: "echo", text: "hello" },
  fill: {},
  ui: {},
};

const AGENT = {
  type: "agent",
  id: "writer",
  role: "Writer",
  instructions: "Write.",
  tools: ["repo.read_file"],
} as unknown as SpecNode;

function panel(node: SpecNode, extra: Partial<Parameters<typeof NodePanel>[0]> = {}) {
  const onEdit = vi.fn<(edit: Edit) => void>();
  const view = render(
    <NodePanel
      node={node}
      manifests={[...NODE_TYPES, ECHO]}
      pending={false}
      error={null}
      retry={() => {}}
      refusal={null}
      onEdit={onEdit}
      {...extra}
    />,
  );
  return { onEdit, ...view };
}

const lastOps = (onEdit: ReturnType<typeof vi.fn>) => (onEdit.mock.lastCall![0] as Edit).ops;

describe("a form for every node type", () => {
  test.each(NODE_TYPES.map((m) => [m.kind, m] as const))("%s", (_kind, manifest) => {
    panel(manifest.default as unknown as SpecNode);
    const form = screen.getByTestId("node-panel").querySelector("form");
    expect(form).not.toBeNull();
    expect(screen.getByRole("heading", { name: new RegExp(manifest.label) })).toBeTruthy();
  });

  test("a kind the web does not know is drawn from its schema", () => {
    const { onEdit } = panel({ type: "echo", id: "echo_1", text: "hello" } as unknown as SpecNode);
    expect(screen.getByText("Says its text back.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Text"), { target: { value: "bye" } });
    expect(lastOps(onEdit)).toEqual([
      { op: "setParam", node_id: "echo_1", path: "text", value: "bye" },
    ]);
  });
});

describe("an agent's parameters", () => {
  test("role and instructions each become one setParam", () => {
    const { onEdit } = panel(AGENT);
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "Editor" } });
    expect(lastOps(onEdit)).toEqual([
      { op: "setParam", node_id: "writer", path: "role", value: "Editor" },
    ]);
    fireEvent.change(screen.getByLabelText("Instructions"), { target: { value: "Edit it." } });
    // The spec is not re-rendered here, so the role's change is still pending beside it.
    expect(lastOps(onEdit)).toContainEqual({
      op: "setParam",
      node_id: "writer",
      path: "instructions",
      value: "Edit it.",
    });
  });

  test("the provider is chosen from the schema's choices, and unset again", () => {
    const { onEdit } = panel(AGENT);
    const provider = screen.getByLabelText(/^Provider/);
    fireEvent.change(provider, { target: { value: "0" } });
    expect(lastOps(onEdit)).toEqual([
      { op: "setParam", node_id: "writer", path: "provider", value: "claude" },
    ]);
  });

  test("tools are ticked from the tools an agent may be granted", () => {
    const { onEdit } = panel(AGENT);
    expect(screen.queryByLabelText("github.openPR")).toBeNull();
    fireEvent.click(screen.getByLabelText("repo.search"));
    expect(lastOps(onEdit)).toEqual([
      {
        op: "setParam",
        node_id: "writer",
        path: "tools",
        value: ["repo.read_file", "repo.search"],
      },
    ]);
    fireEvent.click(screen.getByLabelText("repo.read_file"));
    expect(lastOps(onEdit)).toEqual([
      { op: "setParam", node_id: "writer", path: "tools", value: ["repo.search"] },
    ]);
  });

  test("a value the schema refuses is shown and not kept", () => {
    const { onEdit } = panel(AGENT);
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "" } });
    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  test("a port schema is JSON text in the advanced group; text that does not parse is held", () => {
    const { onEdit } = panel(AGENT);
    expect(screen.queryByLabelText(/^Output schema/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    const output = screen.getByLabelText(/^Output schema/);
    fireEvent.change(output, { target: { value: "{ nope" } });
    expect(screen.getByText(/Not valid JSON/)).toBeTruthy();
    expect(onEdit).not.toHaveBeenCalled();

    fireEvent.change(output, { target: { value: '{"type": "object"}' } });
    expect(lastOps(onEdit)).toEqual([
      { op: "setParam", node_id: "writer", path: "output_schema", value: { type: "object" } },
    ]);
  });

  test("a change from outside, such as an undo, shows in the form", () => {
    const { rerender, onEdit } = panel(AGENT);
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "Editor" } });
    const props = {
      manifests: NODE_TYPES,
      pending: false,
      error: null,
      retry: () => {},
      refusal: null,
      onEdit,
    };
    rerender(<NodePanel node={{ ...AGENT, role: "Editor" } as SpecNode} {...props} />);
    expect((screen.getByLabelText("Role") as HTMLInputElement).value).toBe("Editor");
    rerender(<NodePanel node={AGENT} {...props} />);
    expect((screen.getByLabelText("Role") as HTMLInputElement).value).toBe("Writer");
  });
});

test("a router's routes keep their number and ids; their conditions are edited by index", () => {
  const router = {
    type: "router",
    id: "triage",
    routes: [
      { id: "bug", when: "true", then: { type: "agent", id: "b", role: "b", instructions: "B." } },
      { id: "doc", when: "false", then: { type: "agent", id: "d", role: "d", instructions: "D." } },
    ],
  } as unknown as SpecNode;
  const { onEdit } = panel(router);
  expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Remove item/ })).toBeNull();
  const whens = screen.getAllByLabelText(/^When/);
  fireEvent.change(whens[1], { target: { value: "last == 'docs'" } });
  expect(lastOps(onEdit)).toEqual([
    { op: "setParam", node_id: "triage", path: "routes[1].when", value: "last == 'docs'" },
  ]);
});

test("the panel says when the node types are loading, failed, or unknown", () => {
  const retry = vi.fn();
  const { rerender } = panel(AGENT, { pending: true });
  expect(screen.getByText("Loading node types…")).toBeTruthy();
  const props = { refusal: null, onEdit: () => {}, manifests: [], pending: false };
  rerender(<NodePanel node={AGENT} {...props} error="Could not reach the API." retry={retry} />);
  fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
  expect(retry).toHaveBeenCalled();
  rerender(<NodePanel node={AGENT} {...props} error={null} retry={retry} />);
  expect(screen.getByText("No editable parameters for this kind.")).toBeTruthy();
});

test("a refusal that names the node is shown at the top of its panel", () => {
  panel(AGENT, { refusal: "routes[3] is past the end" });
  expect(screen.getByRole("alert").textContent).toContain("routes[3] is past the end");
});

test("the workflow's budget is set and cleared", () => {
  const spec = { spec_version: "0", id: "flow", name: "Flow", root: AGENT } as WorkflowSpec;
  const onEdit = vi.fn<(edit: Edit) => void>();
  const { rerender } = render(<WorkflowPanel spec={spec} onEdit={onEdit} />);
  const budget = screen.getByLabelText(/^Budget/);
  expect(budget.getAttribute("placeholder")).toBe("No budget");
  fireEvent.change(budget, { target: { value: "2.5" } });
  expect(lastOps(onEdit)).toEqual([{ op: "setParam", path: "budget_usd", value: 2.5 }]);

  rerender(<WorkflowPanel spec={{ ...spec, budget_usd: 2.5 } as WorkflowSpec} onEdit={onEdit} />);
  fireEvent.change(screen.getByLabelText(/^Budget/), { target: { value: "" } });
  expect(lastOps(onEdit)).toEqual([{ op: "setParam", path: "budget_usd", value: null }]);
});
