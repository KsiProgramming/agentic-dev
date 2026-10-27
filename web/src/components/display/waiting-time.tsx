import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";
import { formatDuration } from "@/runs/summaries";

/** How long a run has been paused at gates, apart from its duration: "waiting 12m 04s" while it
 * waits, "waited 1h 00m" after. Nothing when it never waited. */
export function WaitingTime({
  ms,
  live = false,
  className,
  ...props
}: { ms: number; live?: boolean } & Omit<ComponentProps<"span">, "children">) {
  if (ms <= 0 && !live) return null;
  return (
    <span className={cn("tabular-nums", className)} {...props}>
      {live ? "waiting" : "waited"} {formatDuration(ms)}
    </span>
  );
}
