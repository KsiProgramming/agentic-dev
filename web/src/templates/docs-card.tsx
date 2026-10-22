"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { createApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { DEFAULT_WORKSPACE_ID } from "@/settings/claude-connection";

type Repo = components["schemas"]["RepoOut"];

export const DOCS_TEMPLATE_ID = "generate-docs";

type Repos =
  | { state: "loading" }
  | { state: "not-connected" }
  | { state: "failed"; message: string }
  | { state: "connected"; repos: Repo[] };

function failure(err: unknown): string {
  if (err instanceof TypeError) return "Could not reach the API.";
  return err instanceof Error ? err.message : String(err);
}

/** The first reason in a FastAPI error body, or null. */
function reasonOf(error: unknown): string | null {
  if (!error || typeof error !== "object" || !("detail" in error)) return null;
  const detail = error.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    if (first && typeof first === "object" && "msg" in first && typeof first.msg === "string") {
      return first.msg;
    }
  }
  return null;
}

/** Comma- or newline-separated globs, or undefined when there are none. */
function globs(text: string): string[] | undefined {
  const list = text
    .split(/[,\n]/)
    .map((g) => g.trim())
    .filter(Boolean);
  return list.length > 0 ? list : undefined;
}

/** Starts the "Generate docs" template on a repo the GitHub App can reach, then opens the run. */
export function DocsCard({
  baseUrl,
  workspaceId = DEFAULT_WORKSPACE_ID,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const router = useRouter();
  const [repos, setRepos] = useState<Repos>({ state: "loading" });
  const [repo, setRepo] = useState("");
  const [outputDir, setOutputDir] = useState("docs");
  const [include, setInclude] = useState("");
  const [extra, setExtra] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const api = createApiClient(baseUrl);
    const params = { params: { path: { workspace_id: workspaceId } } };
    // Repos only once GitHub is linked: asking first would log an error response in the console.
    const load = async (): Promise<Repos> => {
      const connections = await api.GET("/workspaces/{workspace_id}/connections", params);
      if (!connections.data) {
        return {
          state: "failed",
          message: `Could not load the connections (HTTP ${connections.response.status}).`,
        };
      }
      if (!connections.data.some((c) => c.provider === "github")) {
        return { state: "not-connected" };
      }
      const { data, error, response } = await api.GET("/workspaces/{workspace_id}/repos", params);
      if (data) return { state: "connected", repos: data };
      const detail: unknown = error && "detail" in error ? error.detail : null;
      const code =
        detail && typeof detail === "object" && "code" in detail ? detail.code : undefined;
      if (code === "no_connection" || code === "installation_gone" || response.status === 503) {
        return { state: "not-connected" };
      }
      return { state: "failed", message: `Could not load the repos (HTTP ${response.status}).` };
    };
    load()
      .catch((err: unknown): Repos => ({ state: "failed", message: failure(err) }))
      .then((next) => {
        if (!live) return;
        setRepos(next);
        if (next.state === "connected") setRepo(next.repos[0]?.html_url ?? "");
      });
    return () => {
      live = false;
    };
  }, [baseUrl, workspaceId]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const parameters: Record<string, unknown> = { output_dir: outputDir.trim() || "docs" };
    const patterns = globs(include);
    if (patterns) parameters.include = patterns;
    if (extra.trim()) parameters.extra_instructions = extra.trim();
    try {
      const { data, error, response } = await createApiClient(baseUrl).POST("/runs", {
        body: {
          template: { id: DOCS_TEMPLATE_ID, parameters },
          input: "",
          repo: { url: repo },
          workspace_id: workspaceId,
        },
      });
      if (!data) {
        const reason = reasonOf(error);
        throw new Error(
          `The API refused the run (HTTP ${response.status})${reason ? `: ${reason}` : "."}`,
        );
      }
      router.push(`/runs/${data.run_id}`);
    } catch (err) {
      setError(failure(err));
      setPending(false);
    }
  }

  return (
    <section
      aria-labelledby="docs-card-title"
      className="flex w-full max-w-md flex-col gap-3 rounded border p-4"
    >
      <h2 id="docs-card-title" className="font-semibold">
        Generate docs
      </h2>
      <p className="text-sm text-gray-600">
        Documents each module of a repo in Markdown. You approve before a pull request is opened.
      </p>
      {repos.state === "loading" ? <p className="text-sm text-gray-500">Loading repos…</p> : null}
      {repos.state === "failed" ? (
        <p role="alert" className="text-sm text-red-700">
          {repos.message}
        </p>
      ) : null}
      {repos.state === "not-connected" ? (
        <p className="text-sm">
          Connect GitHub first:{" "}
          <Link href="/settings" className="underline">
            install the GitHub App in Settings
          </Link>
          .
        </p>
      ) : null}
      {repos.state === "connected" && repos.repos.length === 0 ? (
        <p className="text-sm">The GitHub App can reach no repos. Add some on GitHub.</p>
      ) : null}
      {repos.state === "connected" && repos.repos.length > 0 ? (
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            Repository
            <select
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              className="rounded border px-2 py-1"
            >
              {repos.repos.map((r) => (
                <option key={r.id} value={r.html_url}>
                  {r.full_name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Output folder
            <input
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              className="rounded border px-2 py-1 font-mono"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Only these modules (optional)
            <input
              value={include}
              onChange={(e) => setInclude(e.target.value)}
              placeholder="packages/*, web"
              className="rounded border px-2 py-1 font-mono"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Extra instructions (optional)
            <textarea
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="e.g. Write for new contributors."
              className="rounded border px-2 py-1"
            />
          </label>
          <button
            type="submit"
            disabled={pending || !repo}
            className="self-start rounded bg-black px-3 py-1.5 text-white disabled:opacity-50"
          >
            {pending ? "Starting…" : "Generate docs"}
          </button>
        </form>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
