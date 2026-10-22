"use client";

import { FolderGit2Icon, PlugIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState, type FormEvent } from "react";

import { createApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
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
  const id = useId();
  const [attempt, setAttempt] = useState(0);
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
  }, [baseUrl, workspaceId, attempt]);

  function retry() {
    setRepos({ state: "loading" });
    setAttempt((n) => n + 1);
  }

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
    <Card role="region" aria-labelledby="docs-card-title">
      <CardHeader>
        <CardTitle>
          <h2 id="docs-card-title">Generate docs</h2>
        </CardTitle>
        <CardDescription>
          Documents each module of a repo in Markdown. You approve before a pull request is opened.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {repos.state === "loading" ? <LoadingState rows={2} label="Loading repos…" /> : null}
        {repos.state === "failed" ? <ErrorState message={repos.message} onRetry={retry} /> : null}
        {repos.state === "not-connected" ? (
          <EmptyState
            icon={PlugIcon}
            message="Connect GitHub to pick a repository."
            action={
              <Button asChild variant="outline">
                <Link href="/settings">Open Settings to install the GitHub App</Link>
              </Button>
            }
          />
        ) : null}
        {repos.state === "connected" && repos.repos.length === 0 ? (
          <EmptyState
            icon={FolderGit2Icon}
            message="The GitHub App can reach no repos. Add some on GitHub."
          />
        ) : null}
        {repos.state === "connected" && repos.repos.length > 0 ? (
          <form onSubmit={onSubmit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-repo`}>Repository</Label>
              <NativeSelect
                id={`${id}-repo`}
                value={repo}
                onChange={(e) => setRepo(e.target.value)}
                className="w-full"
              >
                {repos.repos.map((r) => (
                  <NativeSelectOption key={r.id} value={r.html_url}>
                    {r.full_name}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-output`}>Output folder</Label>
              <Input
                id={`${id}-output`}
                value={outputDir}
                onChange={(e) => setOutputDir(e.target.value)}
                className="font-mono"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-include`}>Only these modules (optional)</Label>
              <Input
                id={`${id}-include`}
                value={include}
                onChange={(e) => setInclude(e.target.value)}
                placeholder="packages/*, web"
                className="font-mono"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-extra`}>Extra instructions (optional)</Label>
              <Textarea
                id={`${id}-extra`}
                value={extra}
                onChange={(e) => setExtra(e.target.value)}
                maxLength={2000}
                rows={3}
                placeholder="e.g. Write for new contributors."
              />
            </div>
            <Button type="submit" disabled={pending || !repo} className="self-start">
              {pending ? "Starting…" : "Generate docs"}
            </Button>
          </form>
        ) : null}
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}
