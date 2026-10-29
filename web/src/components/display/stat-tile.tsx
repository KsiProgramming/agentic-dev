import { Children, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** One figure with its label and a line of context (a run's cost, its budget under it). It sits
 * in a `StatStrip`, which draws its edges. The secondary line is `foreground-secondary` unless
 * the caller colours it for a status ("waited 1m 52s" in waiting). */
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
      className={cn("flex min-w-0 flex-col gap-0.5 bg-card px-4 py-3", className)}
    >
      <dt className="text-caption font-medium text-muted-foreground">{label}</dt>
      <dd className="truncate text-stat font-semibold tracking-tight tabular-nums">{value}</dd>
      {secondary ? (
        <dd className="truncate text-caption text-foreground-secondary">{secondary}</dd>
      ) : null}
    </dl>
  );
}

const COLUMNS = {
  2: "md:grid-cols-2",
  3: "md:grid-cols-3",
  4: "md:grid-cols-4",
  5: "md:grid-cols-5",
} as const;

/**
 * Stat tiles as one bordered strip split into equal cells (design-language.md → Stat tiles):
 * `columns` cells from 768 px, two columns below that with an odd last tile across both. The
 * lines between cells are the strip's border colour showing through a 1 px gap.
 */
export function StatStrip({
  columns,
  label,
  children,
  className,
}: {
  columns: keyof typeof COLUMNS;
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  const count = Children.toArray(children).filter(Boolean).length;
  return (
    <div
      role={label ? "region" : undefined}
      aria-label={label}
      data-slot="stat-strip"
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border",
        COLUMNS[columns],
        count % 2 === 1 && "[&>*:last-child]:col-span-2 md:[&>*:last-child]:col-span-1",
        className,
      )}
    >
      {children}
    </div>
  );
}
