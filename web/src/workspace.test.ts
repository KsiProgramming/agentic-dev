import { expect, test } from "vitest";

import { DEFAULT_WORKSPACE_ID, workspaceFromCookie } from "./workspace";

const E2E = "00000000-0000-0000-0000-0000000000e2";

test("the cookie names this browser's workspace; without it, the default one", () => {
  expect(workspaceFromCookie(`theme=dark; agentic-workspace=${E2E}`)).toBe(E2E);
  expect(workspaceFromCookie("theme=dark")).toBe(DEFAULT_WORKSPACE_ID);
  expect(workspaceFromCookie("")).toBe(DEFAULT_WORKSPACE_ID);
  // Only an id is taken from it.
  expect(workspaceFromCookie("agentic-workspace=../settings")).toBe(DEFAULT_WORKSPACE_ID);
});
