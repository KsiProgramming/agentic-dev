"use client";

import { cn } from "@/lib/utils";
import { formatAbsolute, formatTimeLeft } from "@/runs/summaries";
import { useNow } from "@/runs/use-now";

import { FOCUSABLE_VALUE, ValueTooltip } from "./value-tooltip";

/** When something runs out, from now ("Expires in 2 d", "Expires in 12 min", then "Expired"),
 * with the exact date and time in a tooltip. Ticks every 30 s unless the page passes its own
 * `now`. */
export function ExpiresIn({
  iso,
  now,
  focusable = true,
  className,
}: {
  iso: string;
  now?: number;
  focusable?: boolean;
  className?: string;
}) {
  const ticking = useNow(30_000, now === undefined);
  return (
    <ValueTooltip content={`Expires ${formatAbsolute(iso)}`}>
      <time
        dateTime={iso}
        tabIndex={focusable ? 0 : undefined}
        className={cn("tabular-nums", focusable && FOCUSABLE_VALUE, className)}
      >
        {formatTimeLeft(iso, now ?? ticking)}
      </time>
    </ValueTooltip>
  );
}
