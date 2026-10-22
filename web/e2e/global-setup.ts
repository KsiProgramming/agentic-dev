import { request } from "@playwright/test";

import { connectClaude, connectGithub } from "./connections";

/** Every e2e test starts from a workspace connected to Claude and to the fake GitHub App. Tests
 * that need another state fake it in the browser (`pretendConnections`); only the journey,
 * which runs after the rest, changes the stack's connections. */
export default async function globalSetup() {
  const api = await request.newContext();
  try {
    await connectClaude(api);
    await connectGithub(api);
  } finally {
    await api.dispose();
  }
}
