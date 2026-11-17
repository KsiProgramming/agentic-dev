import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { JiraConnection as JiraConnectionData } from "@/api/queries";
import { CONNECTIONS_PATH, json, renderWithQueries, requested, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { connectResult, CONNECT_ERRORS, JiraConnection } from "./jira-connection";

const JIRA_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/jira`;
const SCOPES = ["read:jira-work", "write:jira-work", "offline_access"];

const NOT_CONNECTED: JiraConnectionData = {
  configured: true,
  status: "not_connected",
  reason: null,
  account: null,
  scopes: [],
  missing_scopes: [],
  sites: [],
  connected_at: null,
  updated_at: null,
};

const CONNECTED: JiraConnectionData = {
  configured: true,
  status: "connected",
  reason: null,
  account: "Ada Example",
  scopes: SCOPES,
  missing_scopes: [],
  sites: [
    {
      cloud_id: "cloud-acme",
      url: "https://acme.atlassian.net",
      name: "Acme",
      enabled: true,
      projects: [
        {
          id: "10001",
          key: "API",
          name: "Public API",
          fields: {
            acceptance_criteria: { id: "cf_100", name: "Acceptance criteria" },
            story_points: null,
          },
        },
        { id: "10004", key: "WEB", name: "Web shop" },
      ],
    },
    {
      cloud_id: "cloud-labs",
      url: "https://acme-labs.atlassian.net",
      name: "Acme Labs",
      enabled: false,
      projects: [],
    },
  ],
  connected_at: "2026-11-16T10:00:00Z",
  updated_at: "2026-11-16T10:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function card() {
  return within(screen.getByTestId("jira-card"));
}

test("with no Atlassian app on the server, the card says so and offers nothing", async () => {
  stubApi({ [`GET ${JIRA_PATH}`]: () => json(200, { ...NOT_CONNECTED, configured: false }) });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Unavailable")).toBeDefined();
  expect(screen.getByTestId("jira-status").textContent).toContain("not configured on this server");
  expect(card().queryByRole("button")).toBeNull();
});

test("not connected, it offers to connect and sends the browser to Atlassian", async () => {
  const authorizeUrl = "https://auth.atlassian.com/authorize?state=abc";
  const fetch = stubApi({
    [`GET ${JIRA_PATH}`]: () => json(200, NOT_CONNECTED),
    [`POST ${CONNECTIONS_PATH}/jira/authorize`]: () => json(200, { authorize_url: authorizeUrl }),
  });
  const navigate = vi.fn();
  renderWithQueries(<JiraConnection baseUrl="http://api.test" navigate={navigate} />);

  expect(await card().findByText("Not connected")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Connect Jira" }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(authorizeUrl));
  expect(requested(fetch)).toContain(`POST ${CONNECTIONS_PATH}/jira/authorize`);
});

test("connected, it shows the account, each site with its projects and the permissions", async () => {
  stubApi({ [`GET ${JIRA_PATH}`]: () => json(200, CONNECTED) });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Connected")).toBeDefined();
  expect(screen.getByTestId("jira-status").textContent).toContain("Connected as Ada Example");
  const list = screen.getByRole("list", { name: "Jira sites" });
  const sites = within(list)
    .getAllByRole("listitem")
    .filter((li) => li.parentElement === list);
  expect(sites.map((li) => within(li).getByTestId("jira-site-projects").textContent)).toEqual([
    "2 projects",
    "Off · no projects picked",
  ]);
  expect(within(sites[0]!).getByText("acme.atlassian.net")).toBeDefined();
  expect(screen.getByRole("button", { name: "Choose projects of Acme" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Turn on Acme Labs" })).toBeDefined();
  const projects = within(screen.getByRole("list", { name: "Projects of Acme" })).getAllByRole(
    "listitem",
  );
  expect(projects.map((li) => li.textContent)).toEqual(["APIFields mapped", "WEBNo fields mapped"]);
  expect(screen.getByRole("button", { name: "Map fields of Acme" })).toBeDefined();
  expect(screen.queryByRole("button", { name: "Map fields of Acme Labs" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "3 permissions granted" }));
  const scopes = within(screen.getByRole("list", { name: "Permissions" })).getAllByRole("listitem");
  expect(scopes.map((li) => li.textContent)).toEqual(SCOPES);
});

test("a site is turned off with one request", async () => {
  const fetch = stubApi({
    [`GET ${JIRA_PATH}`]: () => json(200, CONNECTED),
    [`PATCH ${JIRA_PATH}/sites/cloud-acme`]: async (request) => {
      expect(await request.json()).toEqual({ enabled: false });
      return json(200, { ...CONNECTED.sites?.[0], enabled: false });
    },
  });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Turn off Acme" }));

  await waitFor(() => expect(requested(fetch)).toContain(`PATCH ${JIRA_PATH}/sites/cloud-acme`));
});

test("disconnecting asks for confirmation, then deletes the connection", async () => {
  const fetch = stubApi({
    [`GET ${JIRA_PATH}`]: () => json(200, CONNECTED),
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, []),
    [`DELETE ${CONNECTIONS_PATH}/jira`]: () => new Response(null, { status: 204 }),
  });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(requested(fetch)).not.toContain(`DELETE ${CONNECTIONS_PATH}/jira`);
  expect(within(dialog).getByRole("link", { name: /connected apps/ })).toBeDefined();
  fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));

  await waitFor(() => expect(requested(fetch)).toContain(`DELETE ${CONNECTIONS_PATH}/jira`));
});

test("a connection Atlassian refuses needs attention and offers to reconnect", async () => {
  stubApi({
    [`GET ${JIRA_PATH}`]: () =>
      json(200, { ...CONNECTED, status: "needs_attention", reason: "invalid_grant" }),
  });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Needs attention")).toBeDefined();
  expect(screen.getByTestId("jira-status").textContent).toContain("refused to renew");
  expect(screen.getByRole("button", { name: "Reconnect" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDefined();
  expect(screen.queryByRole("button", { name: "Choose projects of Acme" })).toBeNull();
});

test("a missing permission is listed as missing", async () => {
  stubApi({
    [`GET ${JIRA_PATH}`]: () =>
      json(200, {
        ...CONNECTED,
        status: "needs_attention",
        reason: "scopes",
        missing_scopes: ["manage:jira-webhook"],
      }),
  });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "3 permissions granted, 1 missing" }));

  expect(screen.getByText("manage:jira-webhook (missing)")).toBeDefined();
});

test("a failed load can be retried", async () => {
  const routes = { [`GET ${JIRA_PATH}`]: () => json(500, { detail: "boom" }) };
  stubApi(routes);
  renderWithQueries(<JiraConnection baseUrl="http://api.test" />);

  expect(await card().findByRole("alert")).toBeDefined();
  routes[`GET ${JIRA_PATH}`] = () => json(200, NOT_CONNECTED);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect(await card().findByText("Not connected")).toBeDefined();
});

test("the callback's result is said once, with a sentence for every reason", () => {
  expect(connectResult()).toBeNull();
  expect(connectResult("connected")).toEqual({ ok: true, text: "Jira connected." });
  expect(connectResult("error", "denied")?.text).toBe(CONNECT_ERRORS.denied);
  expect(connectResult("error", "something-new")).toEqual({
    ok: false,
    text: "Jira was not connected.",
  });
  // Every reason the API's callback can send (`complete_authorize`).
  expect(Object.keys(CONNECT_ERRORS).sort()).toEqual(
    ["atlassian", "denied", "exchange", "no_sites", "not_configured", "scopes", "state"].sort(),
  );
});

test("the result of a consent shows above the card", async () => {
  stubApi({ [`GET ${JIRA_PATH}`]: () => json(200, NOT_CONNECTED) });
  renderWithQueries(<JiraConnection baseUrl="http://api.test" result="error" reason="no_sites" />);

  expect((await screen.findByTestId("jira-result")).textContent).toBe(CONNECT_ERRORS.no_sites);
});
