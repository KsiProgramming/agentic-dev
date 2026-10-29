"use client";

import { useSyncExternalStore } from "react";

/** Whether `query` matches, kept current. False on the server and where `matchMedia` is
 * missing (jsdom). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia?.(query);
      list?.addEventListener("change", onChange);
      return () => list?.removeEventListener("change", onChange);
    },
    () => window.matchMedia?.(query).matches ?? false,
    () => false,
  );
}

/** From 768 px: side sheets; below, bottom sheets and stacked actions (tech-stack → Layout). */
export const MD_UP = "(min-width: 768px)";

/** Below 768 px: a phone, where a selected step opens as a full-height sheet. Asked this way
 * round so that where `matchMedia` is missing (jsdom) the page is not a phone. */
export const PHONE = "(max-width: 767px)";

/** From 1024 px: the gate review sheet's file list and side-by-side diff (tech-stack → Review
 * sheet). */
export const LG_UP = "(min-width: 1024px)";
