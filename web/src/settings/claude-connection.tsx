"use client";

import { useEffect, useState, type FormEvent } from "react";

import { createApiClient } from "@/api/client";
import type { components } from "@/api/schema";

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
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(false);
    }
  }

  if (loaded.state === "loading") {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }
  const { connection } = loaded;

  return (
    <div className="flex w-full max-w-md flex-col gap-3">
      <p data-testid="claude-status" className="text-sm">
        {connection ? (
          <>
            Claude key ending in <span className="font-mono">…{connection.key_hint}</span>, updated{" "}
            {new Date(connection.updated_at).toLocaleString()}.
          </>
        ) : (
          "No Claude key stored. Runs on Claude fail until one is."
        )}
      </p>
      <form onSubmit={onSave} className="flex flex-col gap-2">
        <label className="flex flex-col gap-1 text-sm">
          Claude API key
          <input
            type="password"
            autoComplete="off"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-ant-…"
            className="rounded border px-2 py-1 font-mono"
          />
        </label>
        <button
          type="submit"
          disabled={pending || apiKey.trim() === ""}
          className="rounded bg-black px-3 py-1.5 text-white disabled:opacity-50"
        >
          {connection ? "Replace key" : "Save key"}
        </button>
      </form>
      {connection && !confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          disabled={pending}
          className="self-start text-sm text-red-700 hover:underline"
        >
          Remove key
        </button>
      ) : null}
      {connection && confirming ? (
        <div className="flex items-center gap-3 text-sm">
          <span>Remove the stored key?</span>
          <button
            type="button"
            onClick={onRemove}
            disabled={pending}
            className="rounded bg-red-700 px-2 py-1 text-white disabled:opacity-50"
          >
            Confirm remove
          </button>
          <button type="button" onClick={() => setConfirming(false)} className="hover:underline">
            Cancel
          </button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
