"use client";

import { useState } from "react";

import { createApiClient } from "@/api/client";

import type { PendingGate } from "./gates";

type Decision = "approve" | "reject";

/** Approve or reject the gate a run is waiting at. The gate's input is shown as text only. */
export function GatePanel({
  runId,
  gate,
  baseUrl,
}: {
  runId: string;
  gate: PendingGate;
  baseUrl?: string;
}) {
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: Decision) {
    setPending(true);
    setError(null);
    try {
      const { data, response } = await createApiClient(baseUrl).POST("/runs/{run_id}/approvals", {
        params: { path: { run_id: runId } },
        body: { node_id: gate.nodeId, decision },
      });
      if (!data) throw new Error(`The decision was not accepted (HTTP ${response.status}).`);
      setSent(decision);
    } catch (err) {
      setError(
        err instanceof TypeError
          ? "Could not reach the API."
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      aria-label="Approval"
      data-testid="gate-panel"
      className="mt-4 flex flex-col gap-3 rounded border border-amber-300 bg-amber-50 p-4"
    >
      <h2 className="font-semibold">{gate.title}</h2>
      {gate.prompt ? <p className="text-sm">{gate.prompt}</p> : null}
      {gate.artifact ? (
        <pre className="max-h-64 overflow-auto rounded bg-white p-2 text-xs whitespace-pre-wrap">
          {gate.artifact}
        </pre>
      ) : null}
      {sent ? (
        <p role="status" className="text-sm">
          {sent === "approve" ? "Approved" : "Rejected"}. The run carries on shortly.
        </p>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => decide("approve")}
            disabled={pending}
            className="rounded bg-green-700 px-3 py-1.5 text-white disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => decide("reject")}
            disabled={pending}
            className="rounded border border-red-700 px-3 py-1.5 text-red-700 disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </section>
  );
}
