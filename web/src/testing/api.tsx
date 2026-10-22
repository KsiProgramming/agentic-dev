import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import type { components } from "@/api/schema";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

export const API = "http://api.test";
export const WORKSPACE = `${API}/workspaces/${DEFAULT_WORKSPACE_ID}`;

export function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export type Routes = Record<string, (request: Request) => Response | Promise<Response>>;

/**
 * Stubs `fetch`, answering each request by "METHOD path" (the URL without `http://api.test`,
 * query string included). `routes` can be changed between calls: answers follow it. Returns the
 * mock, whose calls are the requests.
 */
export function stubApi(routes: Routes) {
  const fetch = vi.fn<(r: Request) => Promise<Response>>(async (request) => {
    const key = `${request.method} ${request.url.replace(API, "")}`;
    const respond = routes[key];
    if (!respond) throw new Error(`unexpected ${key}`);
    return respond(request);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** The requests `fetch` was called with, as "METHOD path". */
export function requested(fetch: ReturnType<typeof stubApi>): string[] {
  return fetch.mock.calls.map(([r]) => `${r.method} ${r.url.replace(API, "")}`);
}

/** Renders `ui` with a fresh query cache (no retries, so failures show at once). */
export function renderWithQueries(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

export const CONNECTIONS_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/connections`;
export const REPOS_PATH = `/workspaces/${DEFAULT_WORKSPACE_ID}/repos`;

export const CLAUDE: components["schemas"]["ConnectionOut"] = {
  id: "11111111-1111-1111-1111-111111111111",
  provider: "claude",
  key_hint: "abcd",
  account_login: null,
  manage_url: null,
  created_at: "2026-10-21T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
};

export const GITHUB: components["schemas"]["ConnectionOut"] = {
  id: "22222222-2222-2222-2222-222222222222",
  provider: "github",
  key_hint: null,
  account_login: "acme",
  manage_url: "https://github.com/organizations/acme/settings/installations/42",
  created_at: "2026-10-21T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
};

export const REPOS: components["schemas"]["RepoOut"][] = [
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

/** `GET /templates` as the API lists the docs template. */
export const DOCS_TEMPLATE: components["schemas"]["TemplateOut"] = {
  id: "generate-docs",
  name: "Generate docs",
  description: "Documents each module of the repository.",
  requires: ["claude", "github"],
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      output_dir: {
        default: "docs",
        description: "Where the docs are written, relative to the repository root.",
        maxLength: 100,
        pattern: "^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*/?$",
        title: "Output Dir",
        type: "string",
      },
      include: {
        anyOf: [
          { items: { maxLength: 200, minLength: 1, type: "string" }, maxItems: 20, type: "array" },
          { type: "null" },
        ],
        default: null,
        description: "Glob patterns over module paths.",
        title: "Include",
      },
      extra_instructions: {
        anyOf: [{ maxLength: 2000, type: "string" }, { type: "null" }],
        default: null,
        description: "Preferences for every agent of the run.",
        title: "Extra Instructions",
      },
    },
  },
};

/** `GET …/repos` of a workspace not linked to GitHub. */
export function noGithub() {
  return json(409, {
    detail: { code: "no_connection", message: "the workspace has no GitHub connection" },
  });
}
