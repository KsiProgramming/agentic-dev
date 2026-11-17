import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { JiraConnection, JiraTrigger, Template } from "@/api/queries";
import { DOCS_TEMPLATE, json, renderWithQueries, requested, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { checkTrigger } from "./jira-trigger-sheet";
import { JiraTriggers } from "./jira-triggers";

const WS = `/workspaces/${DEFAULT_WORKSPACE_ID}`;
const RUN = "9f8e7d6c-0000-4000-8000-000000000000";

const CONNECTED: JiraConnection = {
  configured: true,
  status: "connected",
  reason: null,
  account: "Ada Example",
  scopes: [],
  missing_scopes: [],
  sites: [
    {
      cloud_id: "cloud-acme",
      url: "https://acme.atlassian.net",
      name: "Acme",
      enabled: true,
      projects: [{ id: "10001", key: "API", name: "Public API" }],
    },
  ],
  webhooks: [
    {
      cloud_id: "cloud-acme",
      state: "listening",
      error: null,
      expires_at: "2026-12-17T10:00:00Z",
      renewed_at: "2026-11-17T10:00:00Z",
    },
  ],
  connected_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:00Z",
};

const RULE: JiraTrigger = {
  id: "11111111-0000-4000-8000-000000000000",
  cloud_id: "cloud-acme",
  project_key: "API",
  on: "status",
  value: "In Progress",
  template_id: "jira-issue-answer",
  workflow: null,
  repo: { url: "https://github.com/acme/app", ref: null },
  enabled: true,
  created_at: "2026-11-17T10:00:00Z",
  updated_at: "2026-11-17T10:00:00Z",
  last: {
    at: "2026-11-17T11:00:00Z",
    outcome: "started",
    issue_key: "API-1",
    run_id: RUN,
    reason: null,
  },
};

const JIRA_TEMPLATE: Template = {
  ...DOCS_TEMPLATE,
  id: "jira-issue-answer",
  name: "Answer a Jira issue",
  requires: ["claude", "github", "jira"],
  input: { required: true, label: "Which Jira issue?", kind: "jira_issue" },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(overrides: Record<string, () => Response> = {}) {
  return {
    [`GET ${WS}/jira`]: () => json(200, CONNECTED),
    [`GET ${WS}/jira/triggers`]: () => json(200, { triggers: [RULE] }),
    "GET /templates": () => json(200, [DOCS_TEMPLATE, JIRA_TEMPLATE]),
    ...overrides,
  };
}

function card() {
  return within(screen.getByTestId("jira-triggers-card"));
}

test("lists each rule as a sentence, what it runs and what it last did", async () => {
  stubApi(routes());
  renderWithQueries(<JiraTriggers baseUrl="http://api.test" />);

  const [row] = await card().findAllByTestId("jira-trigger");
  const cells = within(row!);
  expect(row!.textContent).toContain("When an issue in API moves to In Progress");
  expect(cells.getByText("Answer a Jira issue")).toBeDefined();
  expect(cells.getByText("acme/app")).toBeDefined();
  expect(cells.getByText("Started a run")).toBeDefined();
  expect(cells.getByText("API-1")).toBeDefined();
  expect(card().getByTestId("jira-listening").textContent).toContain("Listening");
});

test("a site Jira cannot reach says why", async () => {
  const failed = {
    ...CONNECTED,
    webhooks: [{ ...CONNECTED.webhooks![0]!, state: "failed" as const, error: "url_conflict" }],
  };
  stubApi(routes({ [`GET ${WS}/jira`]: () => json(200, failed) }));
  renderWithQueries(<JiraTriggers baseUrl="http://api.test" />);

  const line = await card().findByTestId("jira-listening");
  expect(line.textContent).toContain("Not listening");
  expect(line.textContent).toContain("another address");
});

test("without a Jira connection it points to Integrations and asks for no rules", async () => {
  const fetch = stubApi(
    routes({ [`GET ${WS}/jira`]: () => json(200, { ...CONNECTED, status: "not_connected" }) }),
  );
  renderWithQueries(<JiraTriggers baseUrl="http://api.test" />);

  expect(await card().findByText("Connect Jira to start runs from its issues.")).toBeDefined();
  expect(card().getByRole("link", { name: "Open Integrations" }).getAttribute("href")).toBe(
    "/settings/integrations",
  );
  expect(requested(fetch)).not.toContain(`GET ${WS}/jira/triggers`);
});

test("with no rule yet, it says so", async () => {
  stubApi(routes({ [`GET ${WS}/jira/triggers`]: () => json(200, { triggers: [] }) }));
  renderWithQueries(<JiraTriggers baseUrl="http://api.test" />);
  expect(await card().findByText("No trigger yet.")).toBeDefined();
});

test("a rule is turned off from its row", async () => {
  const fetch = stubApi({
    ...routes(),
    [`PATCH ${WS}/jira/triggers/${RULE.id}`]: () => json(200, { ...RULE, enabled: false }),
  });
  renderWithQueries(<JiraTriggers baseUrl="http://api.test" />);

  const [toggle] = await card().findAllByRole("button", {
    name: "Turn off the trigger: API moves to In Progress",
  });
  fireEvent.click(toggle!);

  await waitFor(() => expect(requested(fetch)).toContain(`PATCH ${WS}/jira/triggers/${RULE.id}`));
  const patch = fetch.mock.calls.find(([r]) => r.method === "PATCH")?.[0];
  expect(await patch?.json()).toEqual({ enabled: false });
});

test("a rule is deleted only after confirming", async () => {
  const fetch = stubApi({
    ...routes(),
    [`DELETE ${WS}/jira/triggers/${RULE.id}`]: () => new Response(null, { status: 204 }),
  });
  renderWithQueries(<JiraTriggers baseUrl="http://api.test" />);

  const [remove] = await card().findAllByRole("button", {
    name: "Delete the trigger: API moves to In Progress",
  });
  fireEvent.click(remove!);
  expect(requested(fetch)).not.toContain(`DELETE ${WS}/jira/triggers/${RULE.id}`);
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

  await waitFor(() => expect(requested(fetch)).toContain(`DELETE ${WS}/jira/triggers/${RULE.id}`));
});

test("the form is checked before it is sent", () => {
  expect(checkTrigger({ on: "status", value: "", target: "", ref: "" })).toEqual({
    value: "Pick a status.",
    target: "Pick what runs.",
  });
  expect(
    checkTrigger({ on: "label", value: "two words", target: "template:x", ref: "" }).value,
  ).toBe("A Jira label has no spaces.");
  expect(checkTrigger({ on: "label", value: "agent", target: "template:x", ref: "a..b" })).toEqual({
    ref: "A branch name cannot hold “..”.",
  });
  expect(checkTrigger({ on: "status", value: "Done", target: "workflow:w", ref: "" })).toEqual({});
});
