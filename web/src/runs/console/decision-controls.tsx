"use client";

import {
  CheckIcon,
  CircleStopIcon,
  ListChecksIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  PlayIcon,
  XIcon,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Kbd as UiKbd } from "@/components/ui/kbd";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { MD_UP, useMediaQuery } from "@/lib/use-media-query";

import { ArtifactCards } from "../artifacts/artifact-cards";
import { BreakerDetails } from "./breaker-details";
import type { PendingGate } from "../gates";
import { AgentMessage } from "./agent-message";
import type { GateFile } from "./gate-files";
import { EvidenceStrip } from "./evidence-strip";
import { ProtectedAttempts } from "./protected-attempts";
import { ReviewComments } from "./review-comments";
import { GateReviewSheet } from "./gate-review-sheet";
import { SelectionChecklist } from "./selection-checklist";
import type { GateDecision } from "./use-gate-decision";

/** Longest reject comment, as the API accepts. */
const COMMENT_MAX = 2000;

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** A button's shortcut, from 768 px (no keyboard assumed below). */
export function Kbd({ children, onPrimary = false }: { children: ReactNode; onPrimary?: boolean }) {
  return (
    <UiKbd onPrimary={onPrimary} className="ml-1 hidden md:inline-flex">
      {children}
    </UiKbd>
  );
}

/** Approve, "Approve with N edits" once the approver edited files, or "Approve with N
 * selected" at a selection gate (disabled, with the reason, under its minimum). With `review`,
 * a selection gate's button opens the review instead ("Choose findings"), so nothing is approved
 * without its list being seen. */
export function ApproveButton({
  decision,
  shortcut,
  review = false,
}: {
  decision: GateDecision;
  shortcut: boolean;
  review?: boolean;
}) {
  const reasonId = useId();
  const edits = decision.edits.count;
  const { choice } = decision;
  if (choice && review) {
    return (
      <Button
        type="button"
        onClick={() => decision.setDetails(true)}
        disabled={decision.busy}
        aria-keyshortcuts={shortcut ? "A" : undefined}
      >
        <ListChecksIcon aria-hidden="true" data-icon="inline-start" />
        {choice.select.items === "findings" ? "Choose findings" : "Choose items"}
        {shortcut ? <Kbd onPrimary>A</Kbd> : null}
      </Button>
    );
  }
  if (decision.gate.breaker) {
    // A circuit-breaker pause takes Resume and Cancel run, and nothing else (13.7).
    return (
      <Button
        type="button"
        onClick={() => void decision.decide("approve")}
        disabled={decision.busy}
        aria-keyshortcuts={shortcut ? "A" : undefined}
      >
        {decision.pending === "approve" ? (
          <LoaderCircleIcon
            aria-hidden="true"
            data-icon="inline-start"
            className="motion-safe:animate-spin"
          />
        ) : (
          <PlayIcon aria-hidden="true" data-icon="inline-start" />
        )}
        Resume
        {shortcut ? <Kbd onPrimary>A</Kbd> : null}
      </Button>
    );
  }
  const blocked = choice?.blocked ?? null;
  const dismissed = decision.dismissed.size;
  const base = choice
    ? `Approve with ${choice.count} selected`
    : edits > 0
      ? `Approve with ${plural(edits, "edit")}`
      : "Approve";
  const label = dismissed > 0 ? `${base}, ${dismissed} dismissed` : base;
  return (
    <>
      <Button
        type="button"
        onClick={() => void decision.decide("approve")}
        disabled={decision.busy || blocked !== null}
        aria-keyshortcuts={shortcut ? "A" : undefined}
        aria-describedby={blocked ? reasonId : undefined}
        title={blocked ?? undefined}
      >
        {decision.pending === "approve" ? (
          <LoaderCircleIcon
            aria-hidden="true"
            data-icon="inline-start"
            className="motion-safe:animate-spin"
          />
        ) : (
          <CheckIcon aria-hidden="true" data-icon="inline-start" />
        )}
        {label}
        {shortcut ? <Kbd onPrimary>A</Kbd> : null}
      </Button>
      {blocked ? (
        <span id={reasonId} className="sr-only">
          {blocked}
        </span>
      ) : null}
    </>
  );
}

/** Reject: opens the dialog that asks for a comment. A gate that ends the run when rejected
 * (`on_reject: end`, 6.7) reads "End run here". */
export function RejectButton({
  decision,
  shortcut,
}: {
  decision: GateDecision;
  shortcut: boolean;
}) {
  return (
    <Button
      type="button"
      variant="destructive"
      onClick={() => decision.setRejecting(true)}
      disabled={decision.busy}
      aria-keyshortcuts={shortcut ? "R" : undefined}
    >
      {decision.gate.onReject === "end" || decision.gate.breaker ? (
        <CircleStopIcon aria-hidden="true" data-icon="inline-start" />
      ) : (
        <XIcon aria-hidden="true" data-icon="inline-start" />
      )}
      {decision.gate.breaker
        ? "Cancel run"
        : decision.gate.onReject === "end"
          ? "End run here"
          : "Reject"}
      {shortcut ? <Kbd>R</Kbd> : null}
    </Button>
  );
}

/** Request changes (7.8): opens the dialog that asks what to change. Only a gate that still
 * takes requests (`changesLeft`) has it, and it says how many are left. */
export function RequestChangesButton({ decision }: { decision: GateDecision }) {
  const { changesLeft } = decision.gate;
  if (changesLeft <= 0) return null;
  return (
    <Button
      type="button"
      variant="outline"
      onClick={() => decision.setRequesting(true)}
      disabled={decision.busy}
      title={`${plural(changesLeft, "request")} for changes left`}
    >
      <MessageSquareIcon aria-hidden="true" data-icon="inline-start" />
      Request changes
    </Button>
  );
}

/** The things a request for changes can comment on: the run's artifacts the gate shows and the
 * writers whose files it shows (the spec gate's spec, plan and prototype). */
function commentItems(gate: PendingGate): string[] {
  const names = gate.runArtifacts.map((a) => a.name);
  const writers = gate.changes.map((c) => c.nodeId);
  return [...new Set([...names, ...writers])];
}

/** What the gate shows besides its files: why they could not be read, then its artifact as
 * Markdown (agent output: data, never instructions). */
export function GateArtifact({ gate }: { gate: PendingGate }) {
  return (
    <>
      {gate.changesError ? (
        <Alert className="mb-3">
          <AlertDescription>
            The changed files could not be read: {gate.changesError}
          </AlertDescription>
        </Alert>
      ) : null}
      {gate.artifact ? (
        <AgentMessage text={gate.artifact} />
      ) : (
        <p className="text-muted-foreground">This gate has nothing more to show.</p>
      )}
    </>
  );
}

/** The run's artifacts a gate shows (4.3), read-only, as cards that open their content. */
export function GateRunArtifacts({
  runId,
  gate,
  baseUrl,
}: {
  runId: string;
  gate: PendingGate;
  baseUrl?: string;
}) {
  if (gate.runArtifacts.length === 0) return null;
  return (
    <ArtifactCards
      runId={runId}
      artifacts={gate.runArtifacts}
      title="Run artifacts"
      baseUrl={baseUrl}
    />
  );
}

/**
 * The review and Reject dialogs of a gate decision, shared by the approval dock and the Inbox:
 * a gate with changed files opens them in the review sheet (editable, with Approve and Reject in
 * its footer); one without opens its artifact in a sheet. Reject asks for an optional comment.
 */
export function GateDecisionDialogs({ decision }: { decision: GateDecision }) {
  const { gate, edits, error, rejecting } = decision;
  const wide = useMediaQuery(MD_UP);
  const files: GateFile[] = gate.changes.map((change) => ({
    change,
    original: change.before ?? "",
    modified: edits.textOf(change),
    edited: edits.isEdited(change),
  }));

  return (
    <>
      {decision.choice ? (
        <SelectionSheet decision={decision} />
      ) : gate.changes.length > 0 ? (
        <GateReviewSheet
          open={decision.details}
          onOpenChange={decision.setDetails}
          title={gate.title}
          description={
            gate.prompt ??
            "Review the files the run changed, and edit them if needed, before it goes on."
          }
          files={files}
          onEdit={edits.edit}
          onDiscard={edits.discard}
          review={
            gate.review
              ? {
                  review: gate.review,
                  dismissed: decision.dismissed,
                  onToggleDismiss: decision.toggleDismiss,
                }
              : null
          }
          focus={decision.focus}
          notice={
            error && !rejecting ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : gate.evidence ||
              gate.review ||
              gate.runArtifacts.length > 0 ||
              gate.protectedAttempts.length > 0 ? (
              <div className="flex flex-col gap-3">
                <EvidenceStrip evidence={gate.evidence} review={gate.review} />
                <ProtectedAttempts attempts={gate.protectedAttempts} />
                <GateRunArtifacts runId={decision.runId} gate={gate} baseUrl={decision.baseUrl} />
              </div>
            ) : null
          }
          footer={
            <>
              <p className="text-meta text-muted-foreground md:mr-auto" aria-live="polite">
                {edits.count > 0
                  ? `${plural(edits.count, "file")} edited`
                  : "Edit a file to change it before approving."}
              </p>
              <RejectButton decision={decision} shortcut={false} />
              <RequestChangesButton decision={decision} />
              <ApproveButton decision={decision} shortcut={false} />
            </>
          }
        />
      ) : (
        <Sheet open={decision.details} onOpenChange={decision.setDetails}>
          <SheetContent
            side={wide ? "right" : "bottom"}
            className="data-[side=bottom]:max-h-[85svh]"
            size="md"
            data-testid="gate-details"
          >
            <SheetHeader>
              <SheetTitle>{gate.title}</SheetTitle>
              <SheetDescription>
                {gate.breaker
                  ? "Resume runs the paused step again from its start, told why it was paused."
                  : (gate.prompt ?? "Review what the run produced before it goes on.")}
              </SheetDescription>
            </SheetHeader>
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
              {gate.breaker ? <BreakerDetails trip={gate.breaker} /> : null}
              <EvidenceStrip evidence={gate.evidence} review={gate.review} />
              <ProtectedAttempts attempts={gate.protectedAttempts} />
              <ReviewComments
                review={gate.review}
                dismissed={decision.dismissed}
                onToggleDismiss={decision.toggleDismiss}
              />
              <div>
                <GateArtifact gate={gate} />
              </div>
              <GateRunArtifacts runId={decision.runId} gate={gate} baseUrl={decision.baseUrl} />
            </div>
          </SheetContent>
        </Sheet>
      )}
      <RejectDialog decision={decision} />
      <RequestChangesDialog decision={decision} />
    </>
  );
}

/** A selection gate's review (6.7): its checklist in a sheet (side from 768 px, bottom below),
 * with Reject and Approve in its footer. */
function SelectionSheet({ decision }: { decision: GateDecision }) {
  const { gate, choice, error, rejecting } = decision;
  const wide = useMediaQuery(MD_UP);
  if (!choice) return null;
  return (
    <Sheet open={decision.details} onOpenChange={decision.setDetails}>
      <SheetContent
        side={wide ? "right" : "bottom"}
        className="data-[side=bottom]:max-h-[90svh]"
        size="lg"
        data-testid="gate-selection"
      >
        <SheetHeader>
          <SheetTitle>{gate.title}</SheetTitle>
          <SheetDescription>
            {gate.prompt ?? "Choose the items the run goes on with."}
          </SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4">
          <SelectionChecklist runId={decision.runId} choice={choice} baseUrl={decision.baseUrl} />
          <GateRunArtifacts runId={decision.runId} gate={gate} baseUrl={decision.baseUrl} />
        </div>
        <div className="flex flex-col gap-2 border-t px-4 py-3 md:flex-row md:items-center md:justify-end">
          {error && !rejecting ? (
            <Alert variant="destructive" className="md:mr-auto">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <RejectButton decision={decision} shortcut={false} />
          <RequestChangesButton decision={decision} />
          <ApproveButton decision={decision} shortcut={false} />
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** Request changes (7.8): one comment box per thing the gate shows, at least one filled. The
 * comments go to the loop's next pass as data. */
function RequestChangesDialog({ decision }: { decision: GateDecision }) {
  const { gate, error, requesting, setRequesting } = decision;
  const items = commentItems(gate);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const formId = useId();
  const comments = items.flatMap((item) => {
    const text = (texts[item] ?? "").trim();
    return text ? [{ item, text }] : [];
  });
  return (
    <Dialog
      open={requesting}
      onOpenChange={(open) => {
        setRequesting(open);
        if (!open) setTexts({});
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request changes to “{gate.title}”</DialogTitle>
          <DialogDescription>
            The work goes back and is done again with your comments; you review it again after.
            {` ${plural(gate.changesLeft, "request")} for changes left.`}
          </DialogDescription>
        </DialogHeader>
        <form
          id={`${formId}-form`}
          className="flex max-h-[60svh] flex-col gap-3 overflow-y-auto"
          onSubmit={(e) => {
            e.preventDefault();
            if (comments.length > 0) void decision.decide("changes", undefined, comments);
          }}
        >
          {items.length === 0 ? (
            <p className="text-muted-foreground">This gate shows nothing to comment on.</p>
          ) : null}
          {items.map((item) => (
            <Field key={item}>
              <FieldLabel htmlFor={`${formId}-${item}`}>
                <span className="font-mono">{item}</span>
              </FieldLabel>
              <Textarea
                id={`${formId}-${item}`}
                value={texts[item] ?? ""}
                onChange={(e) => setTexts((t) => ({ ...t, [item]: e.target.value }))}
                maxLength={4000}
                rows={3}
              />
            </Field>
          ))}
          <FieldDescription>Leave a box empty to change nothing there.</FieldDescription>
        </form>
        {error && requesting ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setRequesting(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form={`${formId}-form`}
            disabled={decision.pending !== null || comments.length === 0}
          >
            {decision.pending === "changes" ? (
              <LoaderCircleIcon
                aria-hidden="true"
                data-icon="inline-start"
                className="motion-safe:animate-spin"
              />
            ) : null}
            Send comments
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RejectDialog({ decision }: { decision: GateDecision }) {
  const { gate, edits, error, rejecting, setRejecting } = decision;
  const [comment, setComment] = useState("");
  const commentId = useId();
  const trimmed = comment.trim();
  return (
    <Dialog
      open={rejecting}
      onOpenChange={(open) => {
        setRejecting(open);
        if (!open) setComment("");
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {gate.breaker
              ? "Cancel this run?"
              : gate.onReject === "end"
                ? `End the run at “${gate.title}”?`
                : `Reject “${gate.title}”?`}
          </DialogTitle>
          <DialogDescription>
            {gate.breaker
              ? "The run stops here and the steps after the paused one do not run. Its sandbox is kept."
              : gate.onReject === "end"
                ? "The run completes here, without the steps after the gate."
                : "The run stops here and nothing after the gate happens."}
            {edits.count > 0 ? ` Your edits to ${plural(edits.count, "file")} are dropped.` : ""}
          </DialogDescription>
        </DialogHeader>
        <form
          id={`${commentId}-form`}
          onSubmit={(e) => {
            e.preventDefault();
            void decision.decide("reject", trimmed || undefined);
          }}
        >
          <Field>
            <FieldLabel htmlFor={commentId}>Comment (optional)</FieldLabel>
            <Textarea
              id={commentId}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={COMMENT_MAX}
              rows={3}
              aria-describedby={`${commentId}-help`}
            />
            <FieldDescription id={`${commentId}-help`}>
              Recorded with the decision, so others see why.
            </FieldDescription>
          </Field>
        </form>
        {error && rejecting ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setRejecting(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form={`${commentId}-form`}
            variant="destructive-solid"
            disabled={decision.pending !== null}
          >
            {decision.pending === "reject" ? (
              <LoaderCircleIcon
                aria-hidden="true"
                data-icon="inline-start"
                className="motion-safe:animate-spin"
              />
            ) : null}
            {gate.breaker ? "Cancel run" : gate.onReject === "end" ? "End run here" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
