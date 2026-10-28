"use client";

import { CheckIcon, LoaderCircleIcon, XIcon } from "lucide-react";
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
import type { PendingGate } from "../gates";
import { AgentMessage } from "./agent-message";
import type { GateFile } from "./gate-files";
import { GateReviewSheet } from "./gate-review-sheet";
import type { GateDecision } from "./use-gate-decision";

/** Longest reject comment, as the API accepts. */
const COMMENT_MAX = 2000;

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="ml-1 hidden rounded border border-current/30 px-1 font-mono text-[11px] leading-4 opacity-70 md:inline">
      {children}
    </kbd>
  );
}

/** Approve, or "Approve with N edits" once the approver edited files. */
export function ApproveButton({
  decision,
  shortcut,
}: {
  decision: GateDecision;
  shortcut: boolean;
}) {
  const edits = decision.edits.count;
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
        <CheckIcon aria-hidden="true" data-icon="inline-start" />
      )}
      {edits > 0 ? `Approve with ${plural(edits, "edit")}` : "Approve"}
      {shortcut ? <Kbd>A</Kbd> : null}
    </Button>
  );
}

/** Reject: opens the dialog that asks for a comment. */
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
      variant="outline"
      onClick={() => decision.setRejecting(true)}
      disabled={decision.busy}
      aria-keyshortcuts={shortcut ? "R" : undefined}
    >
      <XIcon aria-hidden="true" data-icon="inline-start" />
      Reject
      {shortcut ? <Kbd>R</Kbd> : null}
    </Button>
  );
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
      {gate.changes.length > 0 ? (
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
          notice={
            error && !rejecting ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : gate.runArtifacts.length > 0 ? (
              <GateRunArtifacts runId={decision.runId} gate={gate} baseUrl={decision.baseUrl} />
            ) : null
          }
          footer={
            <>
              <p className="text-sm text-muted-foreground md:mr-auto" aria-live="polite">
                {edits.count > 0
                  ? `${plural(edits.count, "file")} edited`
                  : "Edit a file to change it before approving."}
              </p>
              <RejectButton decision={decision} shortcut={false} />
              <ApproveButton decision={decision} shortcut={false} />
            </>
          }
        />
      ) : (
        <Sheet open={decision.details} onOpenChange={decision.setDetails}>
          <SheetContent
            side={wide ? "right" : "bottom"}
            className="data-[side=bottom]:max-h-[85svh] data-[side=right]:w-full! data-[side=right]:sm:max-w-[560px]!"
            data-testid="gate-details"
          >
            <SheetHeader className="border-b pr-12">
              <SheetTitle>{gate.title}</SheetTitle>
              <SheetDescription>
                {gate.prompt ?? "Review what the run produced before it goes on."}
              </SheetDescription>
            </SheetHeader>
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
              <div>
                <GateArtifact gate={gate} />
              </div>
              <GateRunArtifacts runId={decision.runId} gate={gate} baseUrl={decision.baseUrl} />
            </div>
          </SheetContent>
        </Sheet>
      )}
      <RejectDialog decision={decision} />
    </>
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
          <DialogTitle>Reject “{gate.title}”?</DialogTitle>
          <DialogDescription>
            The run stops here and nothing after the gate happens.
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
          <Button type="button" variant="ghost" onClick={() => setRejecting(false)}>
            Cancel
          </Button>
          <Button
            type="submit"
            form={`${commentId}-form`}
            variant="destructive"
            disabled={decision.pending !== null}
          >
            {decision.pending === "reject" ? (
              <LoaderCircleIcon
                aria-hidden="true"
                data-icon="inline-start"
                className="motion-safe:animate-spin"
              />
            ) : null}
            Reject
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
