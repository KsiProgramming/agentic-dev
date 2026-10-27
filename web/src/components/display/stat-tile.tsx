import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** One figure with its label and a line of context (a run's cost, its budget under it). */
export function StatTile({
  label,
  value,
  secondary,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  secondary?: ReactNode;
  className?: string;
}) {
  return (
    <dl
      data-slot="stat-tile"
      className={cn("flex min-w-0 flex-col gap-0.5 rounded-lg border bg-card px-4 py-3", className)}
    >
      <dt className="text-caption text-muted-foreground">{label}</dt>
      <dd className="truncate text-stat font-semibold tabular-nums">{value}</dd>
      {secondary ? (
        <dd className="truncate text-caption text-muted-foreground">{secondary}</dd>
      ) : null}
    </dl>
  );
}
