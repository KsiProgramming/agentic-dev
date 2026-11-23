"use client";

import { useState } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import { ApiError, failure } from "@/api/errors";

import type { GateSelection, PendingGate } from "../gates";
import type { ReviewComment } from "../review";
import { useGateEdits, type GateEdits } from "./use-gate-edits";
import { useGateShortcuts } from "./use-gate-shortcuts";

export type Decision = "approve" | "reject" | "changes";

/** One comment of a request for changes (7.8): on `item`, a thing the gate showed. */
export interface ChangeComment {
  item: string;
  text: string;
}

/** The items chosen at a selection gate (6.7): the preselected ones until the approver changes
 * them. `keys` keeps the gate's item order. */
export interface GateChoice {
  select: GateSelection;
  chosen: ReadonlySet<string>;
  /** The chosen keys, in the gate's item order: what the approval sends. */
  keys: string[];
  count: number;
  /** Why the approval cannot be sent yet (fewer than `select.min` chosen), else null. */
  blocked: string | null;
  toggle: (key: string, on: boolean) => void;
  all: () => void;
  clear: () => void;
}

function useGateChoice(select: GateSelection | null): GateChoice | null {
  const [chosen, setChosen] = useState<ReadonlySet<string>>(
    () => new Set(select?.preselected ?? []),
  );
  if (!select) return null;
  const keys = select.keys.filter((k) => chosen.has(k));
  const short = select.min - keys.length;
  return {
    select,
    chosen,
    keys,
    count: keys.length,
    blocked:
      short > 0 ? `Select at least ${select.min} ${select.min === 1 ? "item" : "items"}.` : null,
    toggle: (key, on) =>
      setChosen((previous) => {
        const next = new Set(previous);
        if (on) next.add(key);
        else next.delete(key);
        return next;
      }),
    all: () => setChosen(new Set(select.keys)),
    clear: () => setChosen(new Set()),
  };
}

/** What the API says when it refuses the dismissals of an approval (13.6), for people. */
const DISMISSAL_REFUSED: Record<string, string> = {
  dismiss_not_allowed: "Comments can only be dismissed when approving.",
  unknown_dismissal:
    "A comment you dismissed is not on this gate. Reload the review and dismiss again.",
  duplicate_dismissal: "A comment was dismissed twice. Reload the review and dismiss again.",
};

/** The comment the approver chose to look at: its file (the writer's node and the path) and
 * line, which the diff opens at. */
export interface ReviewFocus {
  nodeId: string;
  path: string;
  line: number | null;
  /** Bumped by each choice, so choosing the same comment again scrolls to it again. */
  nonce: number;
}

export interface GateDecision {
  runId: string;
  baseUrl: string | undefined;
  gate: PendingGate;
  edits: GateEdits;
  /** A selection gate's chosen items (6.7); null for a gate that does not select. */
  choice: GateChoice | null;
  /** The review comments dismissed so far (13.6); an approval sends them. */
  dismissed: ReadonlySet<string>;
  toggleDismiss: (fingerprint: string) => void;
  /** The comment chosen in the review's list; the review sheet opens at its file and line. */
  focus: ReviewFocus | null;
  /** Opens the review sheet at the comment's file and line. */
  openAt: (comment: ReviewComment) => void;
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
  /** The Request changes dialog is open (7.8). */
  requesting: boolean;
  setRequesting: (open: boolean) => void;
  decide: (decision: Decision, comment?: string, comments?: ChangeComment[]) => Promise<void>;
}

/**
 * A decision at the gate `runId` waits at, as the approval dock and the Inbox both make it: the
 * approver's edits to its files, a selection gate's chosen items, Approve (with the edits or the
 * selection) and Reject (with a comment), a toast once the API took it, and `A` / `R` while
 * `shortcuts` is on. On a selection gate `A` opens the review, so nothing is approved without
 * its list being seen. Key the caller by the gate, so a new gate starts with no edits.
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
  const [requesting, setRequesting] = useState(false);
  const busy = pending !== null || sent !== null;
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const [focus, setFocus] = useState<ReviewFocus | null>(null);
  const edits = useGateEdits(gate.changes);
  const choice = useGateChoice(gate.select);

  function toggleDismiss(fingerprint: string) {
    setDismissed((previous) => {
      const next = new Set(previous);
      if (!next.delete(fingerprint)) next.add(fingerprint);
      return next;
    });
  }

  function openAt(comment: ReviewComment) {
    if (!comment.nodeId) return;
    setFocus((previous) => ({
      nodeId: comment.nodeId ?? "",
      path: comment.path,
      line: comment.line,
      nonce: (previous?.nonce ?? 0) + 1,
    }));
    setDetails(true);
  }

  async function decide(decision: Decision, comment?: string, comments?: ChangeComment[]) {
    if (busy) return;
    if (decision === "approve" && choice?.blocked) {
      setError(choice.blocked);
      return;
    }
    // The dismissals go in the review's own order, whatever order they were chosen in.
    const dismissals =
      decision === "approve"
        ? (gate.review?.comments ?? [])
            .map((c) => c.fingerprint)
            .filter((fingerprint) => dismissed.has(fingerprint))
        : [];
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
          ...(decision === "changes" && comments ? { comments } : {}),
          ...(decision === "approve" && edits.count > 0
            ? {
                edits: edits.edits.map((e) => ({
                  node_id: e.nodeId,
                  path: e.path,
                  content: e.content,
                })),
              }
            : {}),
          ...(decision === "approve" && choice ? { selection: choice.keys } : {}),
          ...(dismissals.length > 0 ? { dismissed: dismissals } : {}),
        },
      });
      if (!data) throw new ApiError(response.status, body, "The decision was not accepted");
      setSent(decision);
      setRejecting(false);
      setRequesting(false);
      setDetails(false);
      // The gate goes away once the run moves on; the toast keeps the outcome visible.
      const done =
        decision === "approve"
          ? "Approved"
          : decision === "changes"
            ? "Changes requested"
            : gate.onReject === "end"
              ? "Ended"
              : "Rejected";
      toast.success(`${done}: ${gate.title}`);
      onDecided?.(decision);
    } catch (err) {
      const refused =
        err instanceof ApiError && err.status === 422 ? DISMISSAL_REFUSED[err.code ?? ""] : null;
      setError(refused ?? failure(err));
    } finally {
      setPending(null);
    }
  }

  useGateShortcuts({
    enabled: shortcuts && !busy,
    onApprove: () => (choice ? setDetails(true) : void decide("approve")),
    onReject: () => setRejecting(true),
  });

  return {
    runId,
    baseUrl,
    gate,
    edits,
    choice,
    dismissed,
    toggleDismiss,
    focus,
    openAt,
    pending,
    sent,
    busy,
    error,
    details,
    setDetails,
    rejecting,
    setRejecting,
    requesting,
    setRequesting,
    decide,
  };
}
