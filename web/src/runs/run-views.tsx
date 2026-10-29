"use client";

import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { tabsListVariants, tabsTriggerVariants, useEdgeFade } from "@/components/ui/tabs";

import { formatCount } from "./cost";
import { RUN_VIEWS, runsQueryToString, type RunsQuery } from "./filters";
import type { RunCounts } from "./use-run-counts";

/** The runs list's saved views as underline tabs in the page header, each with how many runs it
 * holds. Each is a link (the view lives in the URL), the current one marked with `aria-current`. */
export function RunViewTabs({
  query,
  counts,
  pathname,
}: {
  query: RunsQuery;
  counts: RunCounts | undefined;
  pathname: string;
}) {
  const { ref, style } = useEdgeFade<HTMLUListElement>();
  return (
    <nav aria-label="Views">
      <ul ref={ref} style={style} className={tabsListVariants()}>
        {RUN_VIEWS.map((view) => {
          const current = view.id === query.view;
          const search = runsQueryToString({ ...query, view: view.id });
          const count = counts?.[view.id];
          return (
            <li key={view.id} className="flex">
              <Link
                href={search ? `${pathname}?${search}` : pathname}
                scroll={false}
                aria-current={current ? "page" : undefined}
                data-view={view.id}
                className={tabsTriggerVariants({ className: "h-full" })}
              >
                {view.label}
                {count === undefined ? (
                  <Skeleton aria-hidden="true" className="h-3.5 w-4" />
                ) : (
                  <span
                    data-testid={`view-count-${view.id}`}
                    className="font-normal text-muted-foreground tabular-nums"
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
