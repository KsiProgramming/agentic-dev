"use client";

import { CircleAlertIcon, CircleCheckIcon, FolderGit2Icon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  const [attempt, setAttempt] = useState(0);
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
  }, [baseUrl, workspaceId, attempt]);

  function retry() {
    setLoaded({ state: "loading" });
    setAttempt((n) => n + 1);
  }

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
      toast.success("GitHub disconnected.");
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(false);
    }
  }

  const installButton = (label: string) => (
    <Button type="button" onClick={onInstall} disabled={pending} className="self-start">
      {label}
    </Button>
  );

  return (
    <div className="flex w-full flex-col gap-3">
      {banner ? (
        <Alert
          role="status"
          variant={banner.ok ? "default" : "destructive"}
          data-testid="github-result"
        >
          {banner.ok ? (
            <CircleCheckIcon aria-hidden="true" className="text-status-succeeded" />
          ) : (
            <CircleAlertIcon aria-hidden="true" />
          )}
          <AlertDescription className={banner.ok ? "text-foreground" : undefined}>
            {banner.text}
          </AlertDescription>
        </Alert>
      ) : null}
      {loaded.state === "loading" ? <LoadingState rows={2} label="Loading GitHub…" /> : null}
      {loaded.state === "not-configured" ? (
        <p data-testid="github-status" className="text-muted-foreground">
          The GitHub App is not configured on the API. {loaded.detail}
        </p>
      ) : null}
      {loaded.state === "failed" ? <ErrorState message={loaded.message} onRetry={retry} /> : null}
      {loaded.state === "not-connected" ? (
        <>
          <p data-testid="github-status">
            Not connected. Install the GitHub App on your account or organisation to pick repos.
          </p>
          {installButton("Install GitHub App")}
        </>
      ) : null}
      {loaded.state === "gone" ? (
        <>
          <p data-testid="github-status">
            The GitHub App was uninstalled{loaded.login ? ` from ${loaded.login}` : ""} or lost
            access. Install it again.
          </p>
          {installButton("Install GitHub App")}
        </>
      ) : null}
      {loaded.state === "connected" ? (
        <>
          <p data-testid="github-status" className="flex items-start gap-2">
            <CircleCheckIcon
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-status-succeeded"
            />
            <span>
              Installed on <span className="font-medium">{loaded.login ?? "GitHub"}</span>.{" "}
              {loaded.repos.length === 1 ? "1 repo" : `${loaded.repos.length} repos`} available.
            </span>
          </p>
          {loaded.repos.length === 0 ? (
            <EmptyState
              icon={FolderGit2Icon}
              message="The installation has no repos. Add some in its settings on GitHub."
            />
          ) : (
            <ul className="flex flex-col divide-y rounded-lg border" aria-label="Repos">
              {loaded.repos.map((repo) => (
                <li key={repo.id} className="flex min-w-0 items-center gap-2 px-3 py-2">
                  <a
                    href={repo.html_url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate font-mono underline-offset-4 hover:underline"
                  >
                    {repo.full_name}
                  </a>
                  {repo.private ? <Badge variant="outline">private</Badge> : null}
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    {repo.default_branch}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {confirming ? (
            <div className="flex flex-wrap items-center gap-2">
              <span>Disconnect GitHub? The App stays installed on GitHub.</span>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={onDisconnect}
                disabled={pending}
              >
                Confirm disconnect
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(true)}
              disabled={pending}
              className="self-start text-destructive hover:text-destructive"
            >
              Disconnect
            </Button>
          )}
        </>
      ) : null}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
