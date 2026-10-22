"use client";

import { CircleCheckIcon, CircleDashedIcon } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { LoadingState } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Connection = components["schemas"]["ConnectionOut"];

/** The workspace every run belongs to until there are users (mirrors the API's default). */
export const DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001";

type Loaded = { state: "loading" } | { state: "ready"; connection: Connection | null };

function detailOf(error: unknown): string | null {
  if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") {
    return error.detail;
  }
  return null;
}

function failure(err: unknown): string {
  if (err instanceof TypeError) return "Could not reach the API.";
  return err instanceof Error ? err.message : String(err);
}

/** Stores, replaces or removes the workspace's Claude API key. The key is write only: once
 * saved, only its last 4 characters are shown. */
export function ClaudeConnection({
  baseUrl,
  workspaceId = DEFAULT_WORKSPACE_ID,
}: {
  baseUrl?: string;
  workspaceId?: string;
}) {
  const keyId = useId();
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [apiKey, setApiKey] = useState("");
  const [pending, setPending] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const path = { params: { path: { workspace_id: workspaceId } } };

  useEffect(() => {
    let live = true;
    createApiClient(baseUrl)
      .GET("/workspaces/{workspace_id}/connections", {
        params: { path: { workspace_id: workspaceId } },
      })
      .then(({ data, response }) => {
        if (!data) throw new Error(`Could not load the connection (HTTP ${response.status}).`);
        if (live) {
          setLoaded({
            state: "ready",
            connection: data.find((c) => c.provider === "claude") ?? null,
          });
        }
      })
      .catch((err: unknown) => {
        if (live) {
          setError(failure(err));
          setLoaded({ state: "ready", connection: null });
        }
      });
    return () => {
      live = false;
    };
  }, [baseUrl, workspaceId]);

  async function onSave(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const {
        data,
        error: body,
        response,
      } = await createApiClient(baseUrl).PUT("/workspaces/{workspace_id}/connections/claude", {
        ...path,
        body: { api_key: apiKey },
      });
      if (!data) {
        throw new Error(
          response.status === 422
            ? "That does not look like an API key."
            : (detailOf(body) ?? `The API refused the key (HTTP ${response.status}).`),
        );
      }
      setLoaded({ state: "ready", connection: data });
      setApiKey("");
      toast.success("Claude key saved.");
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(false);
    }
  }

  async function onRemove() {
    setPending(true);
    setError(null);
    try {
      const { response } = await createApiClient(baseUrl).DELETE(
        "/workspaces/{workspace_id}/connections/claude",
        path,
      );
      if (!response.ok && response.status !== 404) {
        throw new Error(`Could not remove the key (HTTP ${response.status}).`);
      }
      setLoaded({ state: "ready", connection: null });
      setConfirming(false);
      toast.success("Claude key removed.");
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(false);
    }
  }

  if (loaded.state === "loading") {
    return <LoadingState rows={2} label="Loading the Claude connection…" />;
  }
  const { connection } = loaded;

  return (
    <div className="flex w-full max-w-md flex-col gap-3">
      <p data-testid="claude-status" className="flex items-start gap-2">
        {connection ? (
          <>
            <CircleCheckIcon
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-status-succeeded"
            />
            <span>
              Claude key ending in <span className="font-mono">…{connection.key_hint}</span>,
              updated {new Date(connection.updated_at).toLocaleString()}.
            </span>
          </>
        ) : (
          <>
            <CircleDashedIcon
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            />
            <span>No Claude key stored. Runs on Claude fail until one is.</span>
          </>
        )}
      </p>
      <form onSubmit={onSave} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={keyId}>Claude API key</Label>
          <Input
            id={keyId}
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-ant-…"
            className="font-mono"
          />
        </div>
        <Button type="submit" disabled={pending || apiKey.trim() === ""} className="self-start">
          {connection ? "Replace key" : "Save key"}
        </Button>
      </form>
      {connection && !confirming ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setConfirming(true)}
          disabled={pending}
          className="self-start text-destructive hover:text-destructive"
        >
          Remove key
        </Button>
      ) : null}
      {connection && confirming ? (
        <div className="flex flex-wrap items-center gap-2">
          <span>Remove the stored key?</span>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            onClick={onRemove}
            disabled={pending}
          >
            Confirm remove
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </div>
      ) : null}
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
