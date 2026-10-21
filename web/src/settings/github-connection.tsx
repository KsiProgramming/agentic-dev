"use client";

import { useEffect, useState } from "react";

import { createApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { DEFAULT_WORKSPACE_ID } from "@/settings/claude-connection";

type Repo = components["schemas"]["RepoOut"];

/** What the API's GitHub endpoints say about the workspace. */
type Loaded =
  | { state: "loading" }
  | { state: "not-configured"; detail: string }
  | { state: "not-connected" }
  | { state: "gone"; login: string | null }
  | { state: "connected"; login: string | null; repos: Repo[] }
  | { state: "failed"; message: string };

/** Messages for the `reason` the API's install redirect puts on `/settings?github=error`. */
const INSTALL_ERRORS: Record<string, string> = {
  state: "The install link expired or was already used. Try again.",
  installation: "GitHub did not confirm the installation. Try again.",
  pending: "An organisation owner must approve the install request on GitHub first.",
  github: "GitHub could not be reached. Try again.",
  not_configured: "The GitHub App is not configured on the API.",
};

function detailOf(error: unknown): unknown {
  return error && typeof error === "object" && "detail" in error ? error.detail : null;
}

function codeOf(error: unknown): string | null {
  const detail = detailOf(error);
  if (detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string") {
    return detail.code;
  }
  return null;
}

function failure(err: unknown): string {
  if (err instanceof TypeError) return "Could not reach the API.";
  return err instanceof Error ? err.message : String(err);
}

function installResult(result?: string, reason?: string): { ok: boolean; text: string } | null {
  if (result === "connected") return { ok: true, text: "GitHub App installed." };
  if (result === "error") {
    return { ok: false, text: INSTALL_ERRORS[reason ?? ""] ?? "The install did not complete." };
  }
  return null;
}

/** Links the workspace to the platform's GitHub App and lists the repos it can reach. Installing
 * happens on github.com, which sends the browser back here with `?github=connected|error`. */
export function GithubConnection({
  baseUrl,
  workspaceId = DEFAULT_WORKSPACE_ID,
  result,
  reason,
  navigate = (url) => window.location.assign(url),
}: {
  baseUrl?: string;
  workspaceId?: string;
  /** `github` and `reason` from the page's query string. */
  result?: string;
  reason?: string;
  navigate?: (url: string) => void;
}) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const path = { params: { path: { workspace_id: workspaceId } } };
  const banner = installResult(result, reason);

  useEffect(() => {
    let live = true;
    const api = createApiClient(baseUrl);
    const params = { params: { path: { workspace_id: workspaceId } } };
    Promise.all([
      api.GET("/workspaces/{workspace_id}/connections", params),
      api.GET("/workspaces/{workspace_id}/repos", params),
    ])
      .then(([connections, repos]): Loaded => {
        const login = connections.data?.find((c) => c.provider === "github")?.account_login ?? null;
        if (repos.data) return { state: "connected", login, repos: repos.data };
        const status = repos.response.status;
        const code = codeOf(repos.error);
        if (status === 503) {
          const detail = detailOf(repos.error);
          return {
            state: "not-configured",
            detail: typeof detail === "string" ? detail : "The GitHub App is not configured.",
          };
        }
        if (code === "no_connection") return { state: "not-connected" };
        if (code === "installation_gone") return { state: "gone", login };
        return { state: "failed", message: `Could not load the repos (HTTP ${status}).` };
      })
      .catch((err: unknown): Loaded => ({ state: "failed", message: failure(err) }))
      .then((next) => {
        if (live) setLoaded(next);
      });
    return () => {
      live = false;
    };
  }, [baseUrl, workspaceId]);

  async function onInstall() {
    setPending(true);
    setError(null);
    try {
      const { data, response } = await createApiClient(baseUrl).POST(
        "/workspaces/{workspace_id}/connections/github/install",
        path,
      );
      if (!data) throw new Error(`Could not start the install (HTTP ${response.status}).`);
      navigate(data.install_url);
    } catch (err) {
      setError(failure(err));
      setPending(false);
    }
  }

  async function onDisconnect() {
    setPending(true);
    setError(null);
    try {
      const { response } = await createApiClient(baseUrl).DELETE(
        "/workspaces/{workspace_id}/connections/github",
        path,
      );
      if (!response.ok && response.status !== 404) {
        throw new Error(`Could not disconnect (HTTP ${response.status}).`);
      }
      setLoaded({ state: "not-connected" });
      setConfirming(false);
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(false);
    }
  }

  const installButton = (label: string) => (
    <button
      type="button"
      onClick={onInstall}
      disabled={pending}
      className="self-start rounded bg-black px-3 py-1.5 text-white disabled:opacity-50"
    >
      {label}
    </button>
  );

  return (
    <div className="flex w-full max-w-2xl flex-col gap-3">
      {banner ? (
        <p
          role="status"
          className={`text-sm ${banner.ok ? "text-green-700" : "text-red-700"}`}
          data-testid="github-result"
        >
          {banner.text}
        </p>
      ) : null}
      {loaded.state === "loading" ? <p className="text-sm text-gray-500">Loading…</p> : null}
      {loaded.state === "not-configured" ? (
        <p data-testid="github-status" className="text-sm">
          The GitHub App is not configured on the API. {loaded.detail}
        </p>
      ) : null}
      {loaded.state === "failed" ? (
        <p role="alert" className="text-sm text-red-700">
          {loaded.message}
        </p>
      ) : null}
      {loaded.state === "not-connected" ? (
        <>
          <p data-testid="github-status" className="text-sm">
            Not connected. Install the GitHub App on your account or organisation to pick repos.
          </p>
          {installButton("Install GitHub App")}
        </>
      ) : null}
      {loaded.state === "gone" ? (
        <>
          <p data-testid="github-status" className="text-sm">
            The GitHub App was uninstalled{loaded.login ? ` from ${loaded.login}` : ""} or lost
            access. Install it again.
          </p>
          {installButton("Install GitHub App")}
        </>
      ) : null}
      {loaded.state === "connected" ? (
        <>
          <p data-testid="github-status" className="text-sm">
            Installed on <span className="font-medium">{loaded.login ?? "GitHub"}</span>.{" "}
            {loaded.repos.length === 1 ? "1 repo" : `${loaded.repos.length} repos`} available.
          </p>
          <ul className="flex flex-col divide-y rounded border text-sm" aria-label="Repos">
            {loaded.repos.map((repo) => (
              <li key={repo.id} className="flex items-center gap-2 px-3 py-2">
                <a
                  href={repo.html_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono hover:underline"
                >
                  {repo.full_name}
                </a>
                {repo.private ? (
                  <span className="rounded border px-1.5 text-xs text-gray-600">private</span>
                ) : null}
                <span className="ml-auto text-xs text-gray-500">{repo.default_branch}</span>
              </li>
            ))}
            {loaded.repos.length === 0 ? (
              <li className="px-3 py-2 text-gray-500">
                The installation has no repos. Add some in its settings on GitHub.
              </li>
            ) : null}
          </ul>
          {confirming ? (
            <div className="flex items-center gap-3 text-sm">
              <span>Disconnect GitHub? The App stays installed on GitHub.</span>
              <button
                type="button"
                onClick={onDisconnect}
                disabled={pending}
                className="rounded bg-red-700 px-2 py-1 text-white disabled:opacity-50"
              >
                Confirm disconnect
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="hover:underline"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={pending}
              className="self-start text-sm text-red-700 hover:underline"
            >
              Disconnect
            </button>
          )}
        </>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
