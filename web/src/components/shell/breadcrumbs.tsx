"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

import { breadcrumbsFor } from "./nav";

/** Where the current page sits: its section, then the item inside it, built from the path. */
export function Breadcrumbs({ className }: { className?: string }) {
  const crumbs = breadcrumbsFor(usePathname());
  if (crumbs.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn("min-w-0", className)}>
      <ol className="flex min-w-0 items-center gap-1.5 text-meta text-muted-foreground">
        {crumbs.map((crumb, i) => (
          <li key={i} className={cn("flex min-w-0 items-center gap-1.5", crumb.href && "shrink-0")}>
            {i > 0 ? <ChevronRightIcon aria-hidden="true" className="size-3.5 shrink-0" /> : null}
            {crumb.href ? (
              <Link href={crumb.href} className="rounded-sm hover:text-foreground">
                {crumb.label}
              </Link>
            ) : (
              <span
                aria-current="page"
                title={crumb.title}
                className={cn(
                  "truncate font-medium text-foreground",
                  crumb.mono && "font-mono text-caption",
                )}
              >
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
