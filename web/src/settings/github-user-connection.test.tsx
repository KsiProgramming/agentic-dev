import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { GithubUserConnections } from "@/api/queries";
import { CONNECTIONS_PATH, json, renderWithQueries, requested, stubApi } from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { connectResult, GithubUserConnection } from "./github-user-connection";

const LIST_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/github-user`;
const ADA = "11111111-1111-4111-8111-111111111111";
const GRACE = "22222222-2222-4222-8222-222222222222";

const NONE: GithubUserConnections = { configured: true, connections: [] };
const TWO: GithubUserConnections = {
  configured: true,
  connections: [
    {
      id: ADA,
      login: "ada",
      status: "connected",
      reason: null,
      connected_at: "2026-11-18T10:00:00Z",
      updated_at: "2026-11-18T10:00:00Z",
    },
    {
      id: GRACE,
      login: "grace",
      status: "needs_attention",
      reason: "invalid_grant",
      connected_at: "2026-11-18T11:00:00Z",
      updated_at: "2026-11-18T11:00:00Z",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function card() {
  return within(screen.getByTestId("github-user-card"));
}

test("without an OAuth app the card says so and offers nothing", async () => {
  stubApi({ [`GET ${LIST_PATH}`]: () => json(200, { configured: false, connections: [] }) });
  renderWithQueries(<GithubUserConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Unavailable")).toBeDefined();
  expect(screen.getByTestId("github-user-status").textContent).toContain("not set up");
  expect(card().queryByRole("button")).toBeNull();
});

test("with no account it explains whose Copilot runs and sends the browser to GitHub", async () => {
  const fetch = stubApi({
    [`GET ${LIST_PATH}`]: () => json(200, NONE),
    [`POST ${CONNECTIONS_PATH}/github-user/authorize`]: () =>
      json(200, { authorize_url: "https://github.com/login/oauth/authorize?x=1" }),
  });
  const navigate = vi.fn();
  renderWithQueries(<GithubUserConnection baseUrl="http://api.test" navigate={navigate} />);

  expect(await card().findByText("Not connected")).toBeDefined();
  expect(card().getByText(/company's GitHub connection/)).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Connect your GitHub account" }));

  await waitFor(() =>
    expect(navigate).toHaveBeenCalledWith("https://github.com/login/oauth/authorize?x=1"),
  );
  expect(requested(fetch)).toContain(`POST ${CONNECTIONS_PATH}/github-user/authorize`);
});

test("each account shows its login and status; only one that needs attention can reconnect", async () => {
  stubApi({ [`GET ${LIST_PATH}`]: () => json(200, TWO) });
  renderWithQueries(<GithubUserConnection baseUrl="http://api.test" />);

  const list = await screen.findByRole("list", { name: "Connected GitHub accounts" });
  const [ada, grace] = within(list).getAllByRole("listitem");
  expect(within(ada!).getByText("ada").className).toContain("font-mono");
  expect(within(ada!).getByText("Connected")).toBeDefined();
  expect(within(ada!).queryByRole("button", { name: "Reconnect ada" })).toBeNull();
  expect(within(grace!).getByText("Needs attention")).toBeDefined();
  expect(within(grace!).getByText(/GitHub refused this connection/)).toBeDefined();
  expect(within(grace!).getByRole("button", { name: "Reconnect grace" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Connect another account" })).toBeDefined();
});

test("removing asks for confirmation, then deletes that connection", async () => {
  let removed = false;
  const fetch = stubApi({
    [`GET ${LIST_PATH}`]: () => json(200, removed ? NONE : TWO),
    [`DELETE ${LIST_PATH}/${ADA}`]: () => {
      removed = true;
      return new Response(null, { status: 204 });
    },
  });
  renderWithQueries(<GithubUserConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Remove ada" }));
  expect(requested(fetch)).not.toContain(`DELETE ${LIST_PATH}/${ADA}`);
  const dialog = within(await screen.findByRole("alertdialog"));
  expect(dialog.getByText("Remove ada?")).toBeDefined();
  fireEvent.click(dialog.getByRole("button", { name: "Remove" }));

  await waitFor(() => expect(requested(fetch)).toContain(`DELETE ${LIST_PATH}/${ADA}`));
  expect(await card().findByText("Not connected")).toBeDefined();
});

test("a failed load shows the error with Retry", async () => {
  stubApi({ [`GET ${LIST_PATH}`]: () => json(500, { detail: "boom" }) });
  renderWithQueries(<GithubUserConnection baseUrl="http://api.test" />);

  expect(await card().findByRole("button", { name: "Retry" })).toBeDefined();
});

test("the callback result is shown as a sentence", () => {
  expect(connectResult("connected")).toEqual({ ok: true, text: "GitHub account connected." });
  expect(connectResult("error", "denied")?.text).toContain("Access was not granted");
  expect(connectResult("error", "weird")?.ok).toBe(false);
  expect(connectResult(undefined)).toBeNull();
});

test("the banner appears above the card after the browser comes back", async () => {
  stubApi({ [`GET ${LIST_PATH}`]: () => json(200, TWO) });
  renderWithQueries(
    <GithubUserConnection baseUrl="http://api.test" result="error" reason="state" />,
  );

  expect((await screen.findByTestId("github-user-result")).textContent).toContain("expired");
});
