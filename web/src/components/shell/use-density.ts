"use client";

import { useLayoutEffect, useSyncExternalStore } from "react";

import { DENSITY_KEY } from "./density";

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function storedCompact(): boolean {
  try {
    return localStorage.getItem(DENSITY_KEY) === "compact";
  } catch {
    return false;
  }
}

function setCompact(compact: boolean) {
  document.documentElement.classList.toggle("compact", compact);
  try {
    localStorage.setItem(DENSITY_KEY, compact ? "compact" : "comfortable");
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
  listeners.forEach((listener) => listener());
}

/** Compact mode: table rows of 32 px instead of 40 px (the `compact` class on `<html>`). The
 * choice is kept in this browser. */
export function useCompact(): [boolean, (compact: boolean) => void] {
  const compact = useSyncExternalStore(subscribe, storedCompact, () => false);

  // Puts the class back after React's dev remount clears what the head script set.
  useLayoutEffect(() => {
    document.documentElement.classList.toggle("compact", storedCompact());
  }, []);

  return [compact, setCompact];
}
