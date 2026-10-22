import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  CONNECTIONS_PATH,
  GITHUB,
  json,
  noGithub,
  renderWithQueries,
  REPOS,
  REPOS_PATH,
  requested,
  stubApi,
} from "@/testing/api";

import { GithubConnection } from "./github-connection";

afterEach(() => {
  vi.unstubAllGlobals();
});

function card() {
  return within(screen.getByTestId("github-card"));
}

test("not connected, it offers to install the App and sends the browser to GitHub", async () => {
  const installUrl = "https://github.com/apps/agentic-dev/installations/new?state=abc";
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, []),
    [`GET ${REPOS_PATH}`]: noGithub,
    [`POST ${CONNECTIONS_PATH}/github/install`]: () => json(200, { install_url: installUrl }),
  });
  const navigate = vi.fn();
  renderWithQueries(<GithubConnection baseUrl="http://api.test" navigate={navigate} />);

  expect(await card().findByText("Not connected")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Install GitHub App" }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(installUrl));
  expect(requested(fetch)).toContain(`POST ${CONNECTIONS_PATH}/github/install`);
});

test("connected, it shows the account, a link to manage it and the repos on demand", async () => {
  stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
  });
  renderWithQueries(<GithubConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Connected")).toBeDefined();
  expect(screen.getByTestId("github-status").textContent).toBe("Installed on acme.");
  expect(screen.getByRole("link", { name: /Manage on GitHub/ }).getAttribute("href")).toBe(
    GITHUB.manage_url,
  );

  fireEvent.click(screen.getByRole("button", { name: "2 repositories accessible" }));
  const items = within(screen.getByRole("list", { name: "Repositories" })).getAllByRole("listitem");
  expect(items.map((li) => li.textContent)).toEqual(["acme/apitrunk", "acme/webmain"]);
  expect(screen.getByLabelText("Private")).toBeDefined();
});

test("disconnecting asks for confirmation, then deletes the connection", async () => {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
    [`DELETE ${CONNECTIONS_PATH}/github`]: () => new Response(null, { status: 204 }),
  });
  renderWithQueries(<GithubConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(requested(fetch)).not.toContain(`DELETE ${CONNECTIONS_PATH}/github`);
  fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect" }));

  await waitFor(() => expect(requested(fetch)).toContain(`DELETE ${CONNECTIONS_PATH}/github`));
});

test("a removed installation needs attention and offers to reconnect", async () => {
  stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [GITHUB]),
    [`GET ${REPOS_PATH}`]: () =>
      json(409, { detail: { code: "installation_gone", message: "install it again" } }),
  });
  renderWithQueries(<GithubConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Needs attention")).toBeDefined();
  expect(screen.getByTestId("github-status").textContent).toContain("uninstalled from acme");
  expect(screen.getByRole("button", { name: "Reconnect" })).toBeDefined();
});

test("a server without the App says so and offers nothing to click", async () => {
  stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, []),
    [`GET ${REPOS_PATH}`]: () => json(503, { detail: "set GITHUB_APP_ID" }),
  });
  renderWithQueries(<GithubConnection baseUrl="http://api.test" />);

  expect(await card().findByText("Unavailable")).toBeDefined();
  expect(screen.getByTestId("github-status").textContent).toContain("not configured");
  expect(card().queryByRole("button")).toBeNull();
});

test.each([
  ["connected", undefined, "GitHub App installed."],
  ["error", "state", "The install link expired or was already used. Try again."],
  ["error", "mystery", "The install did not complete."],
])("the install result %s/%s is shown", async (result, reason, text) => {
  stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, []),
    [`GET ${REPOS_PATH}`]: noGithub,
  });
  renderWithQueries(<GithubConnection baseUrl="http://api.test" result={result} reason={reason} />);

  expect(screen.getByTestId("github-result").textContent).toBe(text);
});
