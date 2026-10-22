/** The repo of the user's last started run, per workspace, kept in this browser only. A
 * convenience: storage may be unavailable (private mode, blocked site data), so every access is
 * guarded and a miss just means no preselection. */

function key(workspaceId: string) {
  return `agentic:last-repo:${workspaceId}`;
}

export function loadLastRepo(workspaceId: string): string | null {
  try {
    return window.localStorage.getItem(key(workspaceId));
  } catch {
    return null;
  }
}

export function saveLastRepo(workspaceId: string, repoUrl: string) {
  try {
    window.localStorage.setItem(key(workspaceId), repoUrl);
  } catch {
    // Not remembered; nothing else depends on it.
  }
}
