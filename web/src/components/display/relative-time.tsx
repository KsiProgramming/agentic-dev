"use client";

import { cn } from "@/lib/utils";
import { formatAbsolute, formatClock, formatRelative } from "@/runs/summaries";
import { useNow } from "@/runs/use-now";

import { FOCUSABLE_VALUE, ValueTooltip } from "./value-tooltip";

/** When something happened, relative to now ("5 min ago"), with the exact date and time in a
 * tooltip. A page that shows many times passes its own `now`; otherwise it ticks every minute.
 * A log line shows the time of day instead (`clock`). */
export function RelativeTime({
  iso,
  now,
  clock = false,
  prefix,
  focusable = true,
  className,
}: {
  iso: string;
  now?: number;
  clock?: boolean;
  /** Words before the time, inside the `<time>` ("Started "). */
  prefix?: string;
  focusable?: boolean;
  className?: string;
}) {
  const ticking = useNow(60_000, now === undefined && !clock);
  return (
    <ValueTooltip content={formatAbsolute(iso)}>
      <time
        dateTime={iso}
        tabIndex={focusable ? 0 : undefined}
        className={cn("tabular-nums", focusable && FOCUSABLE_VALUE, className)}
      >
        {prefix}
        {clock ? formatClock(iso) : formatRelative(iso, now ?? ticking)}
      </time>
    </ValueTooltip>
  );
}
