import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { WorkflowSpec } from "@/runs/graph/spec-graph";
import { CLAUDE, CONNECTIONS_PATH, json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { WorkflowRunSheet } from "./new-run-sheet";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const RUN_ID = "00000000-0000-0000-0000-0000000000c4";
const LIST_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/github-user`;
const SETTINGS_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/provider-settings`;
const ADA = "11111111-1111-4111-8111-111111111111";

const ADA_CONNECTED = {
  id: ADA,
  login: "ada",
  status: "connected",
  reason: null,
  connected_at: "2026-11-18T10:00:00Z",
  updated_at: "2026-11-18T10:00:00Z",
} as const;

function spec(steps: unknown[], provider?: "claude" | "copilot"): WorkflowSpec {
  return {
    spec_version: "0",
    id: "docs",
    name: "Docs",
    ...(provider ? { provider } : {}),
    root: { type: "sequence", id: "seq", steps },
  } as unknown as WorkflowSpec;
}

const agent = (id: string, provider?: "claude" | "copilot") => ({
  type: "agent",
  id,
  role: "R",
  instructions: "Go.",
  ...(provider ? { provider } : {}),
});

function show({
  workflow,
  workspaceDefault,
  connected = true,
  claudeKey = true,
  onRun,
}: {
  workflow: WorkflowSpec;
  workspaceDefault?: "claude" | "copilot";
  connected?: boolean;
  claudeKey?: boolean;
  onRun?: () => Response;
}) {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, claudeKey ? [CLAUDE] : []),
    [`GET ${LIST_PATH}`]: () =>
      json(200, { configured: true, connections: connected ? [ADA_CONNECTED] : [] }),
    [`GET ${SETTINGS_PATH}`]: () =>
      json(200, {
        default_provider: workspaceDefault ?? "claude",
        copilot_model: null,
        copilot_credit_usd: 0.01,
        default_copilot_credit_usd: 0.01,
      }),
    "POST /runs": onRun ?? (() => json(202, { run_id: RUN_ID })),
  });
  const navigate = vi.fn();
  renderWithQueries(
    <WorkflowRunSheet
      open
      onOpenChange={() => {}}
      workflow={{ id: "docs", version: 1, name: "Docs", requires: ["claude"], spec: workflow }}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      navigate={navigate}
    />,
  );
  return { fetch, navigate, sheet: within(screen.getByTestId("workflow-run-sheet")) };
}

async function posted(fetch: ReturnType<typeof stubApi>) {
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  return post?.json();
}

async function start(sheet: ReturnType<typeof show>["sheet"]) {
  const button = sheet.getByRole("button", { name: "Start run" });
  await waitFor(() => expect(button).toHaveProperty("disabled", false));
  fireEvent.click(button);
}

test("the workspace default Copilot preselects Copilot and sends provider and account", async () => {
  const { fetch, navigate, sheet } = show({
    workflow: spec([agent("a")]),
    workspaceDefault: "copilot",
  });

  await waitFor(() =>
    expect(sheet.getByRole("radio", { name: /GitHub Copilot/ })).toHaveProperty("checked", true),
  );
  await start(sheet);

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  expect(await posted(fetch)).toMatchObject({ provider: "copilot", copilot_connection_id: ADA });
});

test("the workflow's own provider beats the workspace default", async () => {
  const { sheet } = show({
    workflow: spec([agent("a")], "claude"),
    workspaceDefault: "copilot",
  });

  const claude = await sheet.findByRole("radio", { name: /Claude/ });
  await waitFor(() => expect(sheet.getByRole("radio", { name: /GitHub Copilot/ })).toBeDefined());
  expect(claude).toHaveProperty("checked", true);
});

test("a Copilot default with no usable account stays on Claude", async () => {
  const { sheet } = show({
    workflow: spec([agent("a")]),
    workspaceDefault: "copilot",
    connected: false,
  });

  expect(
    await sheet.findByText("Connect your GitHub account to run on your Copilot."),
  ).toBeDefined();
  expect(sheet.getByRole("radio", { name: /Claude/ })).toHaveProperty("checked", true);
});

test("a node pinned to the other provider is named and the account is sent for it", async () => {
  const { fetch, navigate, sheet } = show({
    workflow: spec([agent("builder"), agent("reviewer", "copilot")]),
  });

  expect(await sheet.findByText("reviewer")).toBeDefined();
  expect(sheet.getByText(/stays on Copilot/)).toBeDefined();
  await start(sheet);

  await waitFor(() => expect(navigate).toHaveBeenCalled());
  expect(await posted(fetch)).toMatchObject({ provider: "claude", copilot_connection_id: ADA });
});

test("a Claude node pinned under a Copilot choice keeps asking for the Claude key", async () => {
  const { sheet } = show({
    workflow: spec([agent("builder", "claude"), agent("reviewer")]),
    claudeKey: false,
  });

  const copilot = await waitFor(() => {
    const radio = sheet.getByRole("radio", { name: /GitHub Copilot/ });
    expect(radio).toHaveProperty("disabled", false);
    return radio;
  });
  fireEvent.click(copilot);

  expect(await sheet.findByRole("button", { name: "Add key" })).toBeDefined();
  expect(sheet.getByText(/stays on Claude/)).toBeDefined();
  expect(sheet.getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
});

test("a run that puts a step on Copilot cannot start without an account, and says so", async () => {
  const { sheet } = show({
    workflow: spec([agent("builder"), agent("reviewer", "copilot")]),
    connected: false,
  });

  expect(await sheet.findByText(/Some steps run on Copilot/)).toBeDefined();
  expect(sheet.getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
});

test("a Claude-only run sends no account", async () => {
  const { fetch, navigate, sheet } = show({ workflow: spec([agent("a")]) });

  await start(sheet);

  await waitFor(() => expect(navigate).toHaveBeenCalled());
  const body = await posted(fetch);
  expect(body).toMatchObject({ provider: "claude" });
  expect(body).not.toHaveProperty("copilot_connection_id");
});

test("the API's copilot_connection_required refusal shows on the choice", async () => {
  const { sheet } = show({
    workflow: spec([agent("a")]),
    onRun: () =>
      json(422, {
        detail:
          "copilot_connection_required: 'a' would run on Copilot, which needs a personal GitHub connection",
      }),
  });

  await start(sheet);

  expect(
    await sheet.findByText("'a' would run on Copilot, which needs a personal GitHub connection"),
  ).toBeDefined();
});
