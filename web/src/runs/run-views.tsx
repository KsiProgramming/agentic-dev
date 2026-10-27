"use client";

import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { formatCount } from "./cost";
import { RUN_VIEWS, runsQueryToString, type RunsQuery } from "./filters";
import type { RunCounts } from "./use-run-counts";

/** The runs list's saved views as tabs, each with how many runs it holds. Each is a link (the
 * view lives in the URL), the current one marked with `aria-current`. */
export function RunViewTabs({
  query,
  counts,
  pathname,
}: {
  query: RunsQuery;
  counts: RunCounts | undefined;
  pathname: string;
}) {
  return (
    <nav aria-label="Views" className="max-w-full overflow-x-auto">
      <ul className="inline-flex h-9 items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground">
        {RUN_VIEWS.map((view) => {
          const current = view.id === query.view;
          const search = runsQueryToString({ ...query, view: view.id });
          const count = counts?.[view.id];
          return (
            <li key={view.id}>
              <Link
                href={search ? `${pathname}?${search}` : pathname}
                scroll={false}
                aria-current={current ? "page" : undefined}
                data-view={view.id}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-body font-medium whitespace-nowrap transition-colors outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
                  current && "bg-background text-foreground shadow-xs",
                )}
              >
                {view.label}
                {count === undefined ? (
                  <Skeleton aria-hidden="true" className="h-3.5 w-4" />
                ) : (
                  <span
                    data-testid={`view-count-${view.id}`}
                    className="text-caption text-muted-foreground tabular-nums"
                  >
                    <span className="sr-only">, </span>
                    {formatCount(count)}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
