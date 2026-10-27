import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { request, type FullConfig } from "@playwright/test";

import { connectClaude, connectGithub } from "./connections";
import { ensureE2eWorkspace, STORAGE_STATE, storageState } from "./workspace";

/** Every e2e test runs in the E2E workspace, never the default one, connected to Claude and to
 * the fake GitHub App. Its browser opens every page there (a cookie in the storage state). Tests
 * that need another state fake it in the browser (`pretendConnections`); only the journey, which
 * runs after the rest, changes the workspace's connections. */
export default async function globalSetup(config: FullConfig) {
  const api = await request.newContext();
  try {
    const workspaceId = await ensureE2eWorkspace(api);
    await connectClaude(api, workspaceId);
    await connectGithub(api, workspaceId);
    const baseURL = config.projects[0]?.use.baseURL ?? "http://localhost:3000";
    mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
    writeFileSync(STORAGE_STATE, JSON.stringify(storageState(workspaceId, baseURL), null, 2));
  } finally {
    await api.dispose();
  }
}
