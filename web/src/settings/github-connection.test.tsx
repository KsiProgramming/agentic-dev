import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { DEFAULT_WORKSPACE_ID } from "./claude-connection";
import { GithubConnection } from "./github-connection";

const WORKSPACE = `http://api.test/workspaces/${DEFAULT_WORKSPACE_ID}`;
const GITHUB_CONNECTION = {
  id: "22222222-2222-2222-2222-222222222222",
  provider: "github",
  key_hint: null,
  account_login: "acme",
  created_at: "2026-10-21T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
};
const REPOS = [
  {
    id: 1,
    full_name: "acme/api",
    name: "api",
    owner: "acme",
    private: true,
    default_branch: "trunk",
    html_url: "https://github.com/acme/api",
  },
  {
    id: 2,
    full_name: "acme/web",
    name: "web",
    owner: "acme",
    private: false,
    default_branch: "main",
    html_url: "https://github.com/acme/web",
  },
];

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Answers each fetch by "METHOD path" (relative to the workspace), recording the requests. */
function api(routes: Record<string, () => Response>) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const key = `${request.method} ${request.url.replace(WORKSPACE, "")}`;
    const respond = routes[key];
    if (!respond) throw new Error(`unexpected ${key}`);
    return respond();
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function notConnected() {
  return {
    "GET /connections": () => json(200, []),
    "GET /repos": () =>
      json(409, {
        detail: { code: "no_connection", message: "the workspace has no GitHub connection" },
      }),
  };
}

test("not connected, it offers to install the App and sends the browser to GitHub", async () => {
  const installUrl = "https://github.com/apps/agentic-dev/installations/new?state=abc";
  const fetch = api({
    ...notConnected(),
    "POST /connections/github/install": () => json(200, { install_url: installUrl }),
  });
  const navigate = vi.fn();
  render(<GithubConnection baseUrl="http://api.test" navigate={navigate} />);

  expect((await screen.findByTestId("github-status")).textContent).toContain("Not connected");
  fireEvent.click(screen.getByRole("button", { name: "Install GitHub App" }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(installUrl));
  expect(fetch.mock.calls.map(([r]) => r.method)).toContain("POST");
});

test("connected, it lists the repos with their visibility and default branch", async () => {
  api({
    "GET /connections": () => json(200, [GITHUB_CONNECTION]),
    "GET /repos": () => json(200, REPOS),
  });

  render(<GithubConnection baseUrl="http://api.test" />);

  expect((await screen.findByTestId("github-status")).textContent).toContain(
    "Installed on acme. 2 repos available.",
  );
  const items = screen.getAllByRole("listitem");
  expect(items.map((li) => li.textContent)).toEqual(["acme/apiprivatetrunk", "acme/webmain"]);
  expect(screen.getByRole("link", { name: "acme/api" }).getAttribute("href")).toBe(
    "https://github.com/acme/api",
  );
});

test("disconnecting asks first, then deletes the connection", async () => {
  const fetch = api({
    "GET /connections": () => json(200, [GITHUB_CONNECTION]),
    "GET /repos": () => json(200, REPOS),
    "DELETE /connections/github": () => new Response(null, { status: 204 }),
  });
  render(<GithubConnection baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
  expect(fetch).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));

  await waitFor(() =>
    expect(screen.getByTestId("github-status").textContent).toContain("Not connected"),
  );
  const del = fetch.mock.calls[2]?.[0] as Request;
  expect(del.method).toBe("DELETE");
  expect(del.url).toBe(`${WORKSPACE}/connections/github`);
});

test("an API without the App says it is not configured and offers no install", async () => {
  api({
    "GET /connections": () => json(200, []),
    "GET /repos": () =>
      json(503, {
        detail:
          "the GitHub App is not configured: set GITHUB_APP_ID, GITHUB_APP_SLUG and " +
          "GITHUB_APP_PRIVATE_KEY_FILE on the API",
      }),
  });

  render(<GithubConnection baseUrl="http://api.test" />);

  expect((await screen.findByTestId("github-status")).textContent).toContain("GITHUB_APP_ID");
  expect(screen.queryByRole("button", { name: "Install GitHub App" })).toBeNull();
});

test("a removed installation asks to install again", async () => {
  api({
    "GET /connections": () => json(200, [GITHUB_CONNECTION]),
    "GET /repos": () =>
      json(409, { detail: { code: "installation_gone", message: "install it again" } }),
  });

  render(<GithubConnection baseUrl="http://api.test" />);

  expect((await screen.findByTestId("github-status")).textContent).toContain(
    "uninstalled from acme",
  );
  expect(screen.getByRole("button", { name: "Install GitHub App" })).toBeDefined();
});

test.each([
  ["connected", undefined, "GitHub App installed."],
  ["error", "state", "The install link expired or was already used. Try again."],
  ["error", "pending", "An organisation owner must approve the install request on GitHub first."],
  ["error", "unknown", "The install did not complete."],
])("the install result %s/%s is shown", async (result, reason, text) => {
  api(notConnected());

  render(<GithubConnection baseUrl="http://api.test" result={result} reason={reason} />);

  expect((await screen.findByTestId("github-result")).textContent).toBe(text);
  await screen.findByTestId("github-status");
});

test("an unreachable API shows an error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

  render(<GithubConnection baseUrl="http://api.test" />);

  expect((await screen.findByRole("alert")).textContent).toBe("Could not reach the API.");
});

test("a failed load can be retried", async () => {
  let calls = 0;
  api({
    "GET /connections": () => json(200, [GITHUB_CONNECTION]),
    "GET /repos": () => (++calls === 1 ? json(500, {}) : json(200, REPOS)),
  });
  render(<GithubConnection baseUrl="http://api.test" />);

  expect((await screen.findByRole("alert")).textContent).toContain("HTTP 500");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect((await screen.findByTestId("github-status")).textContent).toContain("2 repos available");
  expect(screen.queryByRole("alert")).toBeNull();
});
