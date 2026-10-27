"use client";

import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";
import { formatCount, formatTokens, usageDetails, type TokenUsage } from "@/runs/cost";

import { FOCUSABLE_VALUE, ValueTooltip } from "./value-tooltip";

/** A token count in a few characters ("12.3K in"), with the exact count in a tooltip, or every
 * count of `usage` when it is given. */
export function TokenCount({
  value,
  label,
  usage,
  focusable = true,
  className,
  ...props
}: {
  value: number;
  /** What is counted, after the number ("in", "tokens"). */
  label?: string;
  usage?: TokenUsage;
  focusable?: boolean;
} & Omit<ComponentProps<"span">, "children">) {
  return (
    <ValueTooltip content={usage ? usageDetails(usage) : `${formatCount(value)} tokens`}>
      <span
        tabIndex={focusable ? 0 : undefined}
        className={cn("tabular-nums", focusable && FOCUSABLE_VALUE, className)}
        {...props}
      >
        {formatTokens(value)}
        {label ? ` ${label}` : null}
      </span>
    </ValueTooltip>
  );
}
