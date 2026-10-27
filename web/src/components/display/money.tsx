"use client";

import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";
import {
  costCaveat,
  formatCost,
  formatPrice,
  formatUsd,
  usageDetails,
  type TokenUsage,
} from "@/runs/cost";

import { FOCUSABLE_VALUE, ValueTooltip } from "./value-tooltip";

type SpanProps = Omit<ComponentProps<"span">, "children">;

type MoneyProps =
  | {
      /** What some usage cost: "—" when nothing was priced, "≥ $x" when only part of it was.
       * Every token count and the reason for a missing price are in the tooltip. */
      usage: TokenUsage;
      /** The run's budget, shown as "of $x". */
      budget?: number | null;
      focusable?: boolean;
    }
  | {
      /** A plain amount: a `cost` keeps agent-turn precision ("$0.0423"), a `price` is a list
       * price or a limit ("$3.00"). */
      usd: number;
      kind?: "cost" | "price";
    };

/** An amount in USD, in the display locale. */
export function Money(props: MoneyProps & SpanProps) {
  if ("usd" in props) {
    const { usd, kind = "cost", className, ...rest } = props;
    return (
      <span className={cn("tabular-nums", className)} {...rest}>
        {kind === "price" ? formatPrice(usd) : formatUsd(usd)}
      </span>
    );
  }
  const { usage, budget = null, focusable = true, className, ...rest } = props;
  const caveat = costCaveat(usage);
  return (
    <ValueTooltip
      content={
        <>
          <p>{usageDetails(usage)}</p>
          {caveat ? <p>{caveat}</p> : null}
          {budget !== null ? (
            <p>The run stops once its cost reaches its {formatUsd(budget)} budget.</p>
          ) : null}
        </>
      }
    >
      <span
        tabIndex={focusable ? 0 : undefined}
        className={cn("tabular-nums", focusable && FOCUSABLE_VALUE, className)}
        {...rest}
      >
        {formatCost(usage)}
        {budget !== null ? (
          <span className="text-muted-foreground"> of {formatUsd(budget)}</span>
        ) : null}
        {caveat ? <span className="sr-only"> ({caveat})</span> : null}
      </span>
    </ValueTooltip>
  );
}
