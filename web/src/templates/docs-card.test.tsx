import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { DEFAULT_WORKSPACE_ID } from "@/settings/claude-connection";

import { DocsCard } from "./docs-card";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const RUN_ID = "00000000-0000-0000-0000-000000000001";
const WORKSPACE = `http://api.test/workspaces/${DEFAULT_WORKSPACE_ID}`;
const GITHUB = { id: "c1", provider: "github", key_hint: null, account_login: "acme" };
const REPOS = [
  {
    id: 1,
    full_name: "acme/api",
    name: "api",
    owner: "acme",
    private: true,
    default_branch: "main",
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

/** Answers each fetch by "METHOD url" (workspace URLs relative to the workspace). */
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

const CONNECTED = {
  "GET /connections": () => json(200, [GITHUB]),
  "GET /repos": () => json(200, REPOS),
};
const QUEUED = () => json(202, { run_id: RUN_ID, status: "queued", events_url: "x" });

beforeEach(() => push.mockReset());
afterEach(() => vi.unstubAllGlobals());

test("starts the docs template on the chosen repo with its options", async () => {
  const fetch = api({ ...CONNECTED, "POST http://api.test/runs": QUEUED });
  render(<DocsCard baseUrl="http://api.test" />);

  fireEvent.change(await screen.findByLabelText("Repository"), {
    target: { value: "https://github.com/acme/web" },
  });
  fireEvent.change(screen.getByLabelText("Output folder"), { target: { value: "documentation" } });
  fireEvent.change(screen.getByLabelText("Only these modules (optional)"), {
    target: { value: "packages/*, web" },
  });
  fireEvent.change(screen.getByLabelText("Extra instructions (optional)"), {
    target: { value: " Be brief. " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Generate docs" }));

  await waitFor(() => expect(push).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  const request = fetch.mock.calls.at(-1)?.[0] as Request;
  expect(await request.json()).toEqual({
    template: {
      id: "generate-docs",
      parameters: {
        output_dir: "documentation",
        include: ["packages/*", "web"],
        extra_instructions: "Be brief.",
      },
    },
    input: "",
    repo: { url: "https://github.com/acme/web" },
    workspace_id: DEFAULT_WORKSPACE_ID,
  });
});

test("defaults send only the output folder", async () => {
  const fetch = api({ ...CONNECTED, "POST http://api.test/runs": QUEUED });
  render(<DocsCard baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Generate docs" }));

  await waitFor(() => expect(push).toHaveBeenCalled());
  const request = fetch.mock.calls.at(-1)?.[0] as Request;
  const body = (await request.json()) as { template: unknown; repo: unknown };
  expect(body.template).toEqual({ id: "generate-docs", parameters: { output_dir: "docs" } });
  expect(body.repo).toEqual({ url: "https://github.com/acme/api" });
});

test("a refused run shows the API's reason", async () => {
  api({
    ...CONNECTED,
    "POST http://api.test/runs": () =>
      json(422, { detail: [{ msg: "Value error, parameters.output_dir: bad" }] }),
  });
  render(<DocsCard baseUrl="http://api.test" />);

  fireEvent.click(await screen.findByRole("button", { name: "Generate docs" }));

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("HTTP 422");
  expect(alert.textContent).toContain("parameters.output_dir: bad");
  expect(push).not.toHaveBeenCalled();
});

test("without GitHub it links to the settings and never asks for repos", async () => {
  const fetch = api({ "GET /connections": () => json(200, []) });
  render(<DocsCard baseUrl="http://api.test" />);

  const link = await screen.findByRole("link", { name: /install the GitHub App/ });
  expect(link.getAttribute("href")).toBe("/settings");
  expect(screen.queryByRole("button", { name: "Generate docs" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("an uninstalled app counts as not connected", async () => {
  api({
    "GET /connections": () => json(200, [GITHUB]),
    "GET /repos": () => json(404, { detail: { code: "installation_gone", message: "gone" } }),
  });
  render(<DocsCard baseUrl="http://api.test" />);

  expect(await screen.findByRole("link", { name: /install the GitHub App/ })).toBeDefined();
});
