"use client";

import { CheckIcon, CirclePauseIcon, FileSearchIcon, LoaderCircleIcon, XIcon } from "lucide-react";
import { forwardRef, useEffect, useId, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { createApiClient } from "@/api/client";
import { ApiError, failure } from "@/api/errors";
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

import { gateSummary, type PendingGate } from "../gates";
import { AgentMessage } from "./agent-message";
import { useGateShortcuts } from "./use-gate-shortcuts";

type Decision = "approve" | "reject";

/** The dock's element id: the timeline's "Waiting for approval" marker moves focus to it. */
export const DOCK_ID = "approval-dock";

/** Longest reject comment, as the API accepts. */
const COMMENT_MAX = 2000;

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="ml-1 hidden rounded border border-current/30 px-1 font-mono text-[11px] leading-4 opacity-70 md:inline">
      {children}
    </kbd>
  );
}

/** The dock's height, kept in `--dock-height` on the page so other fixed elements (the "Jump to
 * latest" pill) sit above it, and returned so the page can reserve the same space. */
function useDockHeight(element: HTMLElement | null): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    if (!element) return;
    const root = document.documentElement;
    const update = () => {
      const next = Math.ceil(element.getBoundingClientRect().height);
      setHeight(next);
      root.style.setProperty("--dock-height", `${next}px`);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--dock-height");
    };
  }, [element]);
  return height;
}

const DockBar = forwardRef<HTMLElement, { children: ReactNode }>(function DockBar(
  { children },
  ref,
) {
  return (
    <section
      ref={ref}
      id={DOCK_ID}
      tabIndex={-1}
      aria-label="Approval needed"
      data-testid="approval-dock"
      // Above the page, below the header's menus, sheets and dialogs (z-50). It spans the content
      // column only: the sidebar is 4rem wide as a rail (lg) and 15rem in full (xl).
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-background pb-[env(safe-area-inset-bottom)] shadow-[0_-1px_3px_0_rgb(0_0_0/0.06)] outline-none focus-visible:ring-3 focus-visible:ring-ring/50 lg:left-16 xl:left-60"
    >
      {children}
    </section>
  );
});

/**
 * The approval dock (tech-stack → Approval dock): while a gate waits, a bar fixed to the bottom
 * of the viewport with the gate's title, a one-line summary, "Review details", Reject (asks for
 * an optional comment) and Approve. The page keeps an empty block of the dock's height at its
 * end, so the dock never covers content. `A` approves and `R` opens Reject.
 */
export function ApprovalDock({
  runId,
  gate,
  baseUrl,
}: {
  runId: string;
  gate: PendingGate;
  baseUrl?: string;
}) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const height = useDockHeight(element);
  const wide = useMediaQuery(MD_UP);
  const [pending, setPending] = useState<Decision | null>(null);
  const [sent, setSent] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState("");
  const commentId = useId();
  const summary = gateSummary(gate);
  const busy = pending !== null || sent !== null;

  async function decide(decision: Decision, note?: string) {
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
        body: { node_id: gate.nodeId, decision, ...(note ? { comment: note } : {}) },
      });
      if (!data) throw new ApiError(response.status, body, "The decision was not accepted");
      setSent(decision);
      setRejecting(false);
      // The dock goes away once the run moves on; the toast keeps the outcome visible.
      toast.success(`${decision === "approve" ? "Approved" : "Rejected"}: ${gate.title}`);
    } catch (err) {
      setError(failure(err));
    } finally {
      setPending(null);
    }
  }

  useGateShortcuts({
    enabled: !busy,
    onApprove: () => void decide("approve"),
    onReject: () => setRejecting(true),
  });

  const trimmed = comment.trim();

  return (
    <>
      {/* The space the dock takes, so the end of the page scrolls clear of it. */}
      <div aria-hidden="true" data-testid="dock-spacer" style={{ height }} />
      <DockBar ref={setElement}>
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:px-6">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <CirclePauseIcon
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-status-waiting"
            />
            <div className="flex min-w-0 flex-col">
              <h2 className="font-medium">{gate.title}</h2>
              {summary ? (
                <p className="truncate text-sm text-muted-foreground" title={summary}>
                  {summary}
                </p>
              ) : null}
            </div>
          </div>
          {sent ? (
            <p role="status" className="text-sm font-medium">
              {sent === "approve" ? "Approved" : "Rejected"}. The run carries on shortly.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2 md:flex md:shrink-0 md:items-center">
              <Button type="button" variant="ghost" onClick={() => setDetails(true)}>
                <FileSearchIcon aria-hidden="true" data-icon="inline-start" />
                Review details
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setRejecting(true)}
                disabled={busy}
                aria-keyshortcuts="R"
              >
                <XIcon aria-hidden="true" data-icon="inline-start" />
                Reject
                <Kbd>R</Kbd>
              </Button>
              <Button
                type="button"
                onClick={() => void decide("approve")}
                disabled={busy}
                aria-keyshortcuts="A"
              >
                {pending === "approve" ? (
                  <LoaderCircleIcon
                    aria-hidden="true"
                    data-icon="inline-start"
                    className="motion-safe:animate-spin"
                  />
                ) : (
                  <CheckIcon aria-hidden="true" data-icon="inline-start" />
                )}
                Approve
                <Kbd>A</Kbd>
              </Button>
            </div>
          )}
        </div>
        {error ? (
          <div className="mx-auto w-full max-w-5xl px-4 pb-3 md:px-6">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </div>
        ) : null}
      </DockBar>

      <Sheet open={details} onOpenChange={setDetails}>
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
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
            {gate.artifact ? (
              <AgentMessage text={gate.artifact} />
            ) : (
              <p className="text-muted-foreground">This gate has nothing more to show.</p>
            )}
          </div>
        </SheetContent>
      </Sheet>

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
            </DialogDescription>
          </DialogHeader>
          <form
            id={`${commentId}-form`}
            onSubmit={(e) => {
              e.preventDefault();
              void decide("reject", trimmed || undefined);
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
              disabled={pending !== null}
            >
              {pending === "reject" ? (
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
    </>
  );
}
