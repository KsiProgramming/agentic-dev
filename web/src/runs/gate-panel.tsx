"use client";

import { CheckIcon, XIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

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
      // The panel goes away once the run moves on; the toast keeps the outcome visible.
      toast.success(`${decision === "approve" ? "Approved" : "Rejected"}: ${gate.title}`);
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
    <Card
      role="region"
      aria-label="Approval"
      data-testid="gate-panel"
      className="bg-status-waiting-muted ring-status-waiting/40"
    >
      <CardHeader>
        <CardTitle>
          <h2>{gate.title}</h2>
        </CardTitle>
        {gate.prompt ? <CardDescription>{gate.prompt}</CardDescription> : null}
        <CardAction>
          <StatusBadge status="waiting" label="Needs approval" />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {gate.artifact ? (
          <pre className="max-h-64 overflow-auto rounded-md border bg-background p-3 font-mono text-xs whitespace-pre-wrap">
            {gate.artifact}
          </pre>
        ) : null}
        {sent ? (
          <p role="status">
            {sent === "approve" ? "Approved" : "Rejected"}. The run carries on shortly.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => decide("approve")} disabled={pending}>
              <CheckIcon aria-hidden="true" data-icon="inline-start" />
              Approve
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => decide("reject")}
              disabled={pending}
            >
              <XIcon aria-hidden="true" data-icon="inline-start" />
              Reject
            </Button>
          </div>
        )}
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}
