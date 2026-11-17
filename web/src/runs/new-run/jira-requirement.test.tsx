import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { JiraConnection } from "@/api/queries";
import type { WorkflowSpec } from "@/runs/graph/spec-graph";
import {
  CLAUDE,
  CONNECTIONS_PATH,
  GITHUB,
  json,
  renderWithQueries,
  REPOS,
  REPOS_PATH,
  stubApi,
} from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { ConnectionChecklist } from "./connection-checklist";
import { useReadiness, workflowRequires } from "./readiness";

afterEach(() => {
  vi.unstubAllGlobals();
});

const JIRA_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/jira`;
const AUTHORIZE_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/connections/jira/authorize`;
const NOT_CONNECTED: JiraConnection = {
  configured: true,
  status: "not_connected",
  sites: [],
  scopes: [],
  missing_scopes: [],
};

function Checklist({ navigate }: { navigate?: (url: string) => void }) {
  const readiness = useReadiness({ workspaceId: DEFAULT_WORKSPACE_ID, baseUrl: "http://api.test" });
  return (
    <ConnectionChecklist
      requires={["claude", "github", "jira"]}
      readiness={readiness}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      returnTo="/templates?template=jira-issue-answer"
      navigate={navigate}
    />
  );
}

function stub(jira: JiraConnection) {
  return stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE, GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
    [`GET ${JIRA_PATH}`]: () => json(200, jira),
    [`POST ${AUTHORIZE_PATH}`]: () =>
      json(200, { authorize_url: "https://auth.atlassian.com/authorize?x=1" }),
  });
}

async function jiraRow() {
  const row = await waitFor(() => {
    const found = screen
      .getByTestId("connection-checklist")
      .querySelector<HTMLElement>('[data-requirement="jira"]');
    if (!found || found.textContent?.includes("Checking")) throw new Error("not loaded");
    return found;
  });
  return within(row);
}

test("a workflow that names a jira tool needs Jira", () => {
  const spec = {
    id: "w",
    name: "W",
    root: {
      type: "sequence",
      id: "main",
      steps: [
        { type: "agent", id: "a", role: "R", instructions: "Read.", tools: ["jira.getIssue"] },
        { type: "gate", id: "g", title: "Post?" },
        { type: "tool", id: "t", tool: "jira.comment", args: { issue: "A-1", body: "x" } },
      ],
    },
  } as WorkflowSpec;

  expect(workflowRequires(spec)).toEqual(["claude", "jira"]);
});

test("Jira is connected from the checklist and comes back to the sheet", async () => {
  const fetch = stub(NOT_CONNECTED);
  const navigate = vi.fn();
  renderWithQueries(<Checklist navigate={navigate} />);

  const row = await jiraRow();
  expect(row.getByText(/writes to Jira only after you approve/)).toBeDefined();
  fireEvent.click(row.getByRole("button", { name: "Connect Jira" }));

  await waitFor(() =>
    expect(navigate).toHaveBeenCalledWith("https://auth.atlassian.com/authorize?x=1"),
  );
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(await post?.json()).toEqual({ return_to: "/templates?template=jira-issue-answer" });
});

test("a Jira connection that needs attention is reconnected", async () => {
  stub({ ...NOT_CONNECTED, status: "needs_attention", reason: "invalid_grant" });
  renderWithQueries(<Checklist />);

  const row = await jiraRow();
  expect(row.getByText("Atlassian no longer accepts the Jira connection.")).toBeDefined();
  expect(row.getByRole("button", { name: "Reconnect Jira" })).toBeDefined();
});

test("without an Atlassian app on the server there is nothing to connect", async () => {
  stub({ ...NOT_CONNECTED, configured: false });
  renderWithQueries(<Checklist />);

  const row = await jiraRow();
  expect(row.getByText(/Jira is not configured on this server/)).toBeDefined();
  expect(row.queryByRole("button")).toBeNull();
});

test("a connected Jira is ready", async () => {
  stub({ ...NOT_CONNECTED, status: "connected", account: "Ada" });
  renderWithQueries(<Checklist />);

  const row = await jiraRow();
  expect(row.getByText("Connected.")).toBeDefined();
});
