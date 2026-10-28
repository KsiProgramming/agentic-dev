import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";
import { formatPercent } from "@/runs/cost";

/** A share from 0 to 1 as a whole percentage ("67%"), in tabular figures. */
export function Percent({
  value,
  className,
  ...props
}: { value: number } & Omit<ComponentProps<"span">, "children">) {
  return (
    <span className={cn("tabular-nums", className)} {...props}>
      {formatPercent(value)}
    </span>
  );
}
