"use client";

import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { FOCUSABLE_VALUE, ValueTooltip } from "./value-tooltip";

/** `.` (what scanners report for the root) reads "repo root"; other paths as given. */
export function pathLabel(path: string): string {
  return path === "." || path === "./" || path === "" ? "repo root" : path;
}

/**
 * A path that never wraps mid-word (design-language.md → Content rules): one line in mono 12 px,
 * cut from the left when it does not fit (`…/svc/config.py:12`), so the file name and line always
 * show; the full path is in a tooltip. The cut is drawn by the browser (`direction: rtl` with the
 * text isolated left to right), so it follows the box's width.
 */
export function TruncatedPath({
  path,
  focusable = true,
  className,
  ...props
}: { path: string; focusable?: boolean } & Omit<ComponentProps<"span">, "children">) {
  const label = pathLabel(path);
  if (label !== path) {
    return (
      <span className={cn("font-sans text-caption", className)} {...props}>
        {label}
      </span>
    );
  }
  // In a list (`focusable={false}`) the keyboard never stops on it: a native title is enough
  // there, and a long list is not a tooltip per row.
  if (!focusable) {
    return (
      <span
        dir="rtl"
        title={path}
        className={cn("block max-w-full truncate text-left font-mono text-caption", className)}
        {...props}
      >
        <bdi dir="ltr">{path}</bdi>
      </span>
    );
  }
  return (
    <ValueTooltip content={<span className="font-mono break-all">{path}</span>}>
      <span
        dir="rtl"
        tabIndex={focusable ? 0 : undefined}
        className={cn(
          "block max-w-full truncate text-left font-mono text-caption",
          focusable && FOCUSABLE_VALUE,
          className,
        )}
        {...props}
      >
        <bdi dir="ltr">{path}</bdi>
      </span>
    </ValueTooltip>
  );
}
