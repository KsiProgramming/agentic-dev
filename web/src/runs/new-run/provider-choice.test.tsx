import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { GithubUserConnections } from "@/api/queries";
import { CLAUDE, CONNECTIONS_PATH, json, renderWithQueries, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { WorkflowRunSheet } from "./new-run-sheet";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const RUN_ID = "00000000-0000-0000-0000-0000000000c3";
const LIST_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/github-user`;
const ADA = "11111111-1111-4111-8111-111111111111";
const GRACE = "22222222-2222-4222-8222-222222222222";

function account(id: string, login: string, status: "connected" | "needs_attention" = "connected") {
  return {
    id,
    login,
    status,
    reason: status === "connected" ? null : "invalid_grant",
    connected_at: "2026-11-18T10:00:00Z",
    updated_at: "2026-11-18T10:00:00Z",
  } as const;
}

function show(accounts: GithubUserConnections, onRun?: () => Response) {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE]),
    [`GET ${LIST_PATH}`]: () => json(200, accounts),
    "POST /runs": onRun ?? (() => json(202, { run_id: RUN_ID })),
  });
  const navigate = vi.fn();
  renderWithQueries(
    <WorkflowRunSheet
      open
      onOpenChange={() => {}}
      workflow={{ id: "docs", version: 1, name: "Docs", requires: ["claude"] }}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      navigate={navigate}
    />,
  );
  return { fetch, navigate, sheet: within(screen.getByTestId("workflow-run-sheet")) };
}

async function start(sheet: ReturnType<typeof show>["sheet"]) {
  const button = sheet.getByRole("button", { name: "Start run" });
  await waitFor(() => expect(button).toHaveProperty("disabled", false));
  fireEvent.click(button);
}

async function posted(fetch: ReturnType<typeof stubApi>) {
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  return post?.json();
}

test("Claude is the default and sends no Copilot connection", async () => {
  const { fetch, navigate, sheet } = show({ configured: true, connections: [] });

  expect(await sheet.findByRole("radio", { name: /Claude/ })).toHaveProperty("checked", true);
  await start(sheet);

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  expect(await posted(fetch)).not.toHaveProperty("copilot_connection_id");
});

test("with no connected account Copilot is disabled, with why and a link to Integrations", async () => {
  const { sheet } = show({ configured: true, connections: [] });

  const copilot = await sheet.findByRole("radio", { name: /GitHub Copilot/ });
  await waitFor(() =>
    expect(sheet.getByText("Connect your GitHub account to run on your Copilot.")).toBeDefined(),
  );
  expect(copilot).toHaveProperty("disabled", true);
  expect(sheet.getByRole("link", { name: "Integrations" }).getAttribute("href")).toBe(
    "/settings/integrations",
  );
});

test("an account that needs attention says so and cannot be chosen", async () => {
  const { sheet } = show({
    configured: true,
    connections: [account(ADA, "ada", "needs_attention")],
  });

  expect(await sheet.findByText(/needs attention before it can run Copilot/)).toBeDefined();
  expect(sheet.getByRole("radio", { name: /GitHub Copilot/ })).toHaveProperty("disabled", true);
});

test("with one account, picking Copilot names it and sends its connection id", async () => {
  const { fetch, navigate, sheet } = show({ configured: true, connections: [account(ADA, "ada")] });

  const copilot = await waitFor(() => {
    const radio = sheet.getByRole("radio", { name: /GitHub Copilot/ });
    expect(radio).toHaveProperty("disabled", false);
    return radio;
  });
  fireEvent.click(copilot);
  expect(sheet.getByText("ada").className).toContain("font-mono");
  expect(sheet.queryByLabelText("Run as")).toBeNull();
  await start(sheet);

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  expect(await posted(fetch)).toMatchObject({ copilot_connection_id: ADA });
});

test("with several accounts a select picks whose Copilot the run uses", async () => {
  const { fetch, navigate, sheet } = show({
    configured: true,
    connections: [account(ADA, "ada"), account(GRACE, "grace")],
  });

  const copilot = await waitFor(() => {
    const radio = sheet.getByRole("radio", { name: /GitHub Copilot/ });
    expect(radio).toHaveProperty("disabled", false);
    return radio;
  });
  fireEvent.click(copilot);
  fireEvent.change(sheet.getByLabelText("Run as"), { target: { value: GRACE } });
  await start(sheet);

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  expect(await posted(fetch)).toMatchObject({ copilot_connection_id: GRACE });
});

test("a Copilot run needs no Claude key: a workspace with only Copilot can start", async () => {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, []),
    [`GET ${LIST_PATH}`]: () => json(200, { configured: true, connections: [account(ADA, "ada")] }),
    "POST /runs": () => json(202, { run_id: RUN_ID }),
  });
  const navigate = vi.fn();
  renderWithQueries(
    <WorkflowRunSheet
      open
      onOpenChange={() => {}}
      workflow={{ id: "docs", version: 1, name: "Docs", requires: ["claude"] }}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      navigate={navigate}
    />,
  );
  const sheet = within(screen.getByTestId("workflow-run-sheet"));
  const button = sheet.getByRole("button", { name: "Start run" });

  // On Claude the missing key blocks the run, and the checklist asks for it.
  expect(await sheet.findByRole("button", { name: "Add key" })).toBeDefined();
  expect(button).toHaveProperty("disabled", true);

  // On Copilot the key is not needed: the checklist goes and the run can start.
  fireEvent.click(await sheet.findByRole("radio", { name: /GitHub Copilot/ }));
  await waitFor(() => expect(button).toHaveProperty("disabled", false));
  expect(sheet.queryByRole("button", { name: "Add key" })).toBeNull();
  fireEvent.click(button);

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  expect(await posted(fetch)).toMatchObject({ copilot_connection_id: ADA });
});

test("the API's refusal of the account shows on the choice", async () => {
  const { sheet } = show({ configured: true, connections: [account(ADA, "ada")] }, () =>
    json(409, {
      detail: { code: "copilot_needs_attention", message: "ada needs to reconnect GitHub." },
    }),
  );

  const copilot = await waitFor(() => {
    const radio = sheet.getByRole("radio", { name: /GitHub Copilot/ });
    expect(radio).toHaveProperty("disabled", false);
    return radio;
  });
  fireEvent.click(copilot);
  await start(sheet);

  expect(await sheet.findByText("ada needs to reconnect GitHub.")).toBeDefined();
});
