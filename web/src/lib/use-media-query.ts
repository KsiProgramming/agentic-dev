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
