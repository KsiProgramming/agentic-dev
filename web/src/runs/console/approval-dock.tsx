"use client";

import { CirclePauseIcon, FileSearchIcon } from "lucide-react";
import { forwardRef, useEffect, useState, type ReactNode } from "react";

import { ExpiresIn } from "@/components/display";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { gateSummary, type PendingGate } from "../gates";
import { ApproveButton, GateDecisionDialogs, RejectButton } from "./decision-controls";
import { useGateDecision } from "./use-gate-decision";

/** The dock's element id: the timeline's "Waiting for approval" marker moves focus to it. */
export const DOCK_ID = "approval-dock";

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
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-background pb-[env(safe-area-inset-bottom)] shadow-dock outline-none focus-visible:ring-3 focus-visible:ring-ring/50 lg:left-16 xl:left-60"
    >
      {children}
    </section>
  );
});

/**
 * The approval dock (tech-stack → Approval dock): while a gate waits, a bar fixed to the bottom
 * of the viewport with the gate's title, a one-line summary, "Review details", Reject (asks for
 * an optional comment) and Approve. The page keeps an empty block of the dock's height at its
 * end, so the dock never covers content. `A` approves and `R` opens Reject. A gate with changed
 * files opens them in the review sheet, where the approver may edit them before approving. The
 * decision and its dialogs are the Inbox's too (`useGateDecision`, `GateDecisionDialogs`).
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
  const decision = useGateDecision({ runId, gate, baseUrl, shortcuts: true });
  const { sent, error } = decision;
  const summary = gateSummary(gate);

  return (
    <>
      {/* The space the dock takes, so the end of the page scrolls clear of it. */}
      <div aria-hidden="true" data-testid="dock-spacer" style={{ height }} />
      <DockBar ref={setElement}>
        <div className="mx-auto flex w-full max-w-content flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:px-6">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <CirclePauseIcon
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-status-waiting"
            />
            <div className="flex min-w-0 flex-col">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <h2 className="font-medium">{gate.title}</h2>
                {gate.expiresAt ? (
                  <ExpiresIn iso={gate.expiresAt} className="text-meta text-muted-foreground" />
                ) : null}
              </div>
              {summary ? (
                <p className="truncate text-meta text-foreground-secondary" title={summary}>
                  {summary}
                </p>
              ) : null}
            </div>
          </div>
          {sent ? (
            <p role="status" className="text-meta font-medium">
              {sent === "approve" ? "Approved" : "Rejected"}. The run carries on shortly.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2 md:flex md:shrink-0 md:items-center">
              <Button type="button" variant="ghost" onClick={() => decision.setDetails(true)}>
                <FileSearchIcon aria-hidden="true" data-icon="inline-start" />
                Review details
              </Button>
              <RejectButton decision={decision} shortcut />
              <ApproveButton decision={decision} shortcut review />
            </div>
          )}
        </div>
        {error ? (
          <div className="mx-auto w-full max-w-content px-4 pb-3 md:px-6">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </div>
        ) : null}
      </DockBar>
      <GateDecisionDialogs decision={decision} />
    </>
  );
}
