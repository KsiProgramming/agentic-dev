import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";
import { formatDuration } from "@/runs/summaries";

/** How long something took ("2m 05s"); "—" when it has not started. */
export function Duration({
  ms,
  className,
  ...props
}: { ms: number | null } & Omit<ComponentProps<"span">, "children">) {
  return (
    <span className={cn("tabular-nums", className)} {...props}>
      {ms === null ? "—" : formatDuration(ms)}
    </span>
  );
}
