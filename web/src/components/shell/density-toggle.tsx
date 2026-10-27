"use client";

import { Rows3Icon, Rows4Icon } from "lucide-react";
import { useLayoutEffect, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

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
export function DensityToggle() {
  const compact = useSyncExternalStore(subscribe, storedCompact, () => false);

  // Puts the class back after React's dev remount clears what the head script set.
  useLayoutEffect(() => {
    document.documentElement.classList.toggle("compact", storedCompact());
  }, []);

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label="Compact rows"
      aria-pressed={compact}
      onClick={() => setCompact(!compact)}
    >
      {compact ? <Rows4Icon aria-hidden="true" /> : <Rows3Icon aria-hidden="true" />}
    </Button>
  );
}
