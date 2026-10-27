"use client";

import type { ReactElement, ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

/** Focus ring for a value that takes focus only to show its tooltip. */
export const FOCUSABLE_VALUE =
  "rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50";

/**
 * The details of a value (the exact time, every token count) in a tooltip on hover, and on focus
 * when the value is focusable. In a list where every row shows such values, rows pass
 * `focusable={false}` so the keyboard does not stop on each of them.
 */
export function ValueTooltip({
  content,
  children,
}: {
  content: ReactNode;
  children: ReactElement;
}) {
  if (content === null || content === undefined || content === "") return children;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent className="flex-col items-start">{content}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
