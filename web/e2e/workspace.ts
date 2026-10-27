import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type APIRequestContext } from "@playwright/test";

// The API the browser talks to (compose publishes it on the host).
export const apiURL = process.env.E2E_API_URL ?? "http://localhost:8000";

/** The workspace the e2e tests run in, so their runs never show in the default one (roadmap
 * 11.4). Found by name, made once per stack. */
export const E2E_WORKSPACE_NAME = "E2E";

/** The browser state every test starts from: the cookie that picks the E2E workspace (the web's
 * `WORKSPACE_COOKIE`). Written by the global setup. */
export const STORAGE_STATE = path.join(__dirname, ".state", "storage.json");

const COOKIE = "agentic-workspace";

/** Finds the E2E workspace, or makes it. Returns its id. */
export async function ensureE2eWorkspace(request: APIRequestContext): Promise<string> {
  const listed = await request.get(`${apiURL}/workspaces`);
  expect(listed.status()).toBe(200);
  const workspaces = (await listed.json()) as { id: string; name: string }[];
  const found = workspaces.find((w) => w.name === E2E_WORKSPACE_NAME);
  if (found) return found.id;
  const created = await request.post(`${apiURL}/workspaces`, {
    data: { name: E2E_WORKSPACE_NAME },
  });
  expect(created.status(), await created.text()).toBe(201);
  return ((await created.json()) as { id: string }).id;
}

/** The browser state that opens every page in `workspaceId`. */
export function storageState(workspaceId: string, baseURL: string) {
  return {
    cookies: [
      {
        name: COOKIE,
        value: workspaceId,
        domain: new URL(baseURL).hostname,
        path: "/",
        expires: -1,
        httpOnly: false,
        secure: false,
        sameSite: "Lax" as const,
      },
    ],
    origins: [],
  };
}

let cached: string | undefined;

/** The E2E workspace's id, as the global setup saved it. */
export function e2eWorkspaceId(): string {
  if (!cached) {
    const state = JSON.parse(readFileSync(STORAGE_STATE, "utf8")) as {
      cookies: { name: string; value: string }[];
    };
    cached = state.cookies.find((c) => c.name === COOKIE)?.value;
    if (!cached) throw new Error(`no ${COOKIE} cookie in ${STORAGE_STATE}: run the global setup`);
  }
  return cached;
}
