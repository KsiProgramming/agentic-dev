import { useSyncExternalStore } from "react";

/** The workspace every run belongs to until there are users (mirrors the API's default). */
export const DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001";

/** The cookie that picks another workspace for this browser. Only the e2e tests set it, so their
 * runs stay out of the default workspace; a workspace switcher comes with users. */
export const WORKSPACE_COOKIE = "agentic-workspace";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The workspace named by `cookie` (a `document.cookie` string), else the default one. */
export function workspaceFromCookie(cookie: string): string {
  for (const part of cookie.split(";")) {
    const [name, value] = part.trim().split("=");
    if (name === WORKSPACE_COOKIE && value && UUID.test(value)) return value;
  }
  return DEFAULT_WORKSPACE_ID;
}

// The cookie does not change while a page is open.
const subscribe = () => () => {};

/** `given` if set, else this browser's workspace: the one its cookie names, else the default
 * one. The server render uses the default. */
export function useWorkspaceId(given?: string): string {
  const fromCookie = useSyncExternalStore(
    subscribe,
    () => workspaceFromCookie(document.cookie),
    () => DEFAULT_WORKSPACE_ID,
  );
  return given ?? fromCookie;
}
