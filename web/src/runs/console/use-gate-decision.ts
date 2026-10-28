"use client";

import { useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import { ApiError, failure } from "@/api/errors";

import type { PendingGate } from "../gates";
import { useGateEdits, type GateEdits } from "./use-gate-edits";
import { useGateShortcuts } from "./use-gate-shortcuts";

export type Decision = "approve" | "reject";

export interface GateDecision {
  runId: string;
  baseUrl: string | undefined;
  gate: PendingGate;
  edits: GateEdits;
  /** The decision being sent. */
  pending: Decision | null;
  /** The decision the API accepted. */
  sent: Decision | null;
  /** Sending, or sent: the gate takes no other decision. */
  busy: boolean;
  /** Why the last decision was not accepted. */
  error: string | null;
  /** The review (sheet) is open. */
  details: boolean;
  setDetails: (open: boolean) => void;
  /** The Reject dialog is open. */
  rejecting: boolean;
  setRejecting: (open: boolean) => void;
  decide: (decision: Decision, comment?: string) => Promise<void>;
}

/**
 * A decision at the gate `runId` waits at, as the approval dock and the Inbox both make it: the
 * approver's edits to its files, Approve (with the edits) and Reject (with a comment), a toast
 * once the API took it, and `A` / `R` while `shortcuts` is on. Key the caller by the gate, so a
 * new gate starts with no edits.
 */
export function useGateDecision({
  runId,
  gate,
  baseUrl,
  shortcuts,
  onDecided,
}: {
  runId: string;
  gate: PendingGate;
  baseUrl?: string;
  shortcuts: boolean;
  onDecided?: (decision: Decision) => void;
}): GateDecision {
  const [pending, setPending] = useState<Decision | null>(null);
  const [sent, setSent] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const busy = pending !== null || sent !== null;
  const edits = useGateEdits(gate.changes);

  async function decide(decision: Decision, comment?: string) {
    if (busy) return;
    setPending(decision);
    setError(null);
    try {
      const {
        data,
        error: body,
        response,
      } = await createApiClient(baseUrl).POST("/runs/{run_id}/approvals", {
        params: { path: { run_id: runId } },
        body: {
          node_id: gate.nodeId,
          decision,
          ...(comment ? { comment } : {}),
          ...(decision === "approve" && edits.count > 0
            ? {
                edits: edits.edits.map((e) => ({
                  node_id: e.nodeId,
                  path: e.path,
                  content: e.content,
                })),
              }
            : {}),
        },
      });
      if (!data) throw new ApiError(response.status, body, "The decision was not accepted");
      setSent(decision);
      setRejecting(false);
      setDetails(false);
      // The gate goes away once the run moves on; the toast keeps the outcome visible.
      toast.success(`${decision === "approve" ? "Approved" : "Rejected"}: ${gate.title}`);
      onDecided?.(decision);
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(null);
    }
  }

  useGateShortcuts({
    enabled: shortcuts && !busy,
    onApprove: () => void decide("approve"),
    onReject: () => setRejecting(true),
  });

  return {
    runId,
    baseUrl,
    gate,
    edits,
    pending,
    sent,
    busy,
    error,
    details,
    setDetails,
    rejecting,
    setRejecting,
    decide,
  };
}
