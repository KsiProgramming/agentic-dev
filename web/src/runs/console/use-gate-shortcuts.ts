"use client";

import { useEffect, useRef } from "react";

/** Whether a key press belongs to something else: typing in a field, or a dialog or sheet
 * (which has its own keys) being open. */
function busy(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.repeat) return true;
  if (event.ctrlKey || event.metaKey || event.altKey) return true;
  const target = event.target;
  if (
    target instanceof HTMLElement &&
    (target.isContentEditable || target.closest("input, textarea, select, [contenteditable]"))
  ) {
    return true;
  }
  return document.querySelector('[role="dialog"], [role="alertdialog"]') !== null;
}

/** `A` approves and `R` opens Reject while a gate waits (tech-stack → Approval dock). Not while
 * typing or while a dialog is open. */
export function useGateShortcuts({
  enabled,
  onApprove,
  onReject,
}: {
  enabled: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const handlers = useRef({ onApprove, onReject });
  useEffect(() => {
    handlers.current = { onApprove, onReject };
  });

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (busy(event)) return;
      const key = event.key.toLowerCase();
      if (key === "a") {
        event.preventDefault();
        handlers.current.onApprove();
      } else if (key === "r") {
        event.preventDefault();
        handlers.current.onReject();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
