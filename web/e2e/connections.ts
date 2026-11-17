import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { apiURL, e2eWorkspaceId } from "./workspace";

/** The workspace's connections endpoint. */
export function connectionsURL(workspaceId = e2eWorkspaceId()): string {
  return `${apiURL}/workspaces/${workspaceId}/connections`;
}

/** Accepted by the API's fake key check (`CLAUDE_KEY_CHECK=fake`). */
export const TEST_KEY = "sk-ant-test-e2e-0001";

/** The fake GitHub App's repo (`AGENTIC_GITHUB=fake`), a bare repo seeded by compose. */
export const DOCS_DEMO = "e2e-org/docs-demo";

const FAKES_NEEDED =
  "The e2e tests need the stack's fakes: AGENTIC_GITHUB=fake and CLAUDE_KEY_CHECK=fake " +
  "(see .env.example).";

/** Stores the test Claude key in the workspace. */
export async function connectClaude(request: APIRequestContext, workspaceId = e2eWorkspaceId()) {
  const response = await request.put(`${connectionsURL(workspaceId)}/claude`, {
    data: { api_key: TEST_KEY },
  });
  expect(response.status(), `${FAKES_NEEDED} PUT …/claude said: ${await response.text()}`).toBe(
    200,
  );
}

/** Links the workspace to the fake GitHub App: its install URL leads straight to the API's
 * setup endpoint, which stores the installation. */
export async function connectGithub(request: APIRequestContext, workspaceId = e2eWorkspaceId()) {
  const started = await request.post(`${connectionsURL(workspaceId)}/github/install`);
  expect(started.status(), FAKES_NEEDED).toBe(200);
  const { install_url } = (await started.json()) as { install_url: string };
  expect(install_url, FAKES_NEEDED).toContain("/github/setup?");
  const setup = await request.get(install_url, { maxRedirects: 0 });
  expect(setup.headers().location, FAKES_NEEDED).toContain("github=connected");
}

/** The fake Atlassian's first site and a project on it (`AGENTIC_JIRA=fake`). */
export const JIRA_SITE = "fake-cloud-acme";
export const JIRA_PROJECT = { id: "10001", key: "API" };

/** Connects the workspace to the fake Atlassian (its consent leads straight back to the API's
 * callback) and picks the API project on its first site, as a trigger needs (7.3). */
export async function connectJira(request: APIRequestContext, workspaceId = e2eWorkspaceId()) {
  const needed = "The Jira e2e tests need AGENTIC_JIRA=fake (see .env.example).";
  const started = await request.post(`${connectionsURL(workspaceId)}/jira/authorize`);
  expect(started.status(), needed).toBe(200);
  const { authorize_url } = (await started.json()) as { authorize_url: string };
  const back = await request.get(authorize_url, { maxRedirects: 0 });
  expect(back.headers().location, needed).toContain("jira=connected");
  const picked = await request.put(
    `${apiURL}/workspaces/${workspaceId}/jira/sites/${JIRA_SITE}/projects`,
    { data: { project_ids: [JIRA_PROJECT.id] } },
  );
  expect(picked.status(), await picked.text()).toBe(200);
}

/** Deletes the workspace's Jira triggers, so each test starts with none. */
export async function clearJiraTriggers(
  request: APIRequestContext,
  workspaceId = e2eWorkspaceId(),
) {
  const base = `${apiURL}/workspaces/${workspaceId}/jira/triggers`;
  const listed = await request.get(base);
  expect(listed.status()).toBe(200);
  const { triggers } = (await listed.json()) as { triggers: { id: string }[] };
  for (const trigger of triggers) {
    expect((await request.delete(`${base}/${trigger.id}`)).status()).toBe(204);
  }
}

/** Makes sure the workspace has a Jira trigger, adding one if it has none; never removes any,
 * so specs running side by side can share it. */
export async function ensureJiraTrigger(
  request: APIRequestContext,
  workspaceId = e2eWorkspaceId(),
) {
  await connectJira(request, workspaceId);
  const listed = await request.get(`${apiURL}/workspaces/${workspaceId}/jira/triggers`);
  const { triggers } = (await listed.json()) as { triggers: unknown[] };
  if (triggers.length === 0) await addJiraTrigger(request, workspaceId);
}

/** Adds a trigger through the API: when an API issue moves to In Progress, answer it on the
 * docs demo repo. */
export async function addJiraTrigger(request: APIRequestContext, workspaceId = e2eWorkspaceId()) {
  const created = await request.post(`${apiURL}/workspaces/${workspaceId}/jira/triggers`, {
    data: {
      cloud_id: JIRA_SITE,
      project_key: JIRA_PROJECT.key,
      on: "status",
      value: "In Progress",
      template_id: "jira-issue-answer",
      repo: { url: `https://github.com/${DOCS_DEMO}` },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
}

/** Makes the browser see the workspace with no connection, or with its GitHub App gone,
 * without changing the stack that other tests share. */
export async function pretendConnections(page: Page, state: "none" | "github-gone") {
  await page.route(`**/workspaces/${e2eWorkspaceId()}/connections`, (route) =>
    route.fulfill({
      json:
        state === "none"
          ? []
          : [
              {
                id: "22222222-2222-2222-2222-222222222222",
                provider: "github",
                key_hint: null,
                account_login: "e2e-org",
                manage_url: null,
                created_at: "2026-10-22T10:00:00Z",
                updated_at: "2026-10-22T10:00:00Z",
              },
            ],
    }),
  );
  await page.route(`**/workspaces/${e2eWorkspaceId()}/repos`, (route) =>
    route.fulfill({
      status: 409,
      json: {
        detail:
          state === "none"
            ? { code: "no_connection", message: "the workspace has no GitHub connection" }
            : { code: "installation_gone", message: "install it again" },
      },
    }),
  );
}
