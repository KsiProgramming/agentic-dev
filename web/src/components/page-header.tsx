import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A page's title, a short description and its primary actions: on the right from `md`,
 * stacked under the title below that. `aside` sits beside the title, outside the heading (the
 * run console's status and id); `icon` is a tile before the title (the run's template).
 *
 * The header is a band across the content width with a bottom border (design-language.md →
 * Page header band); `tabs` (page-level underline tabs) sit at its bottom, their bar on that
 * border. Breadcrumbs live in the top bar. */
export function PageHeader({
  title,
  aside,
  description,
  actions,
  icon,
  tabs,
  className,
}: {
  title: ReactNode;
  aside?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  tabs?: ReactNode;
  className?: string;
}) {
  return (
    <header
      data-slot="page-header"
      // Bleeds over the shell's padding (px-4, md:px-8; py-6) so the border spans the content.
      className={cn(
        "-mx-4 -mt-6 flex flex-col gap-4 border-b bg-background px-4 pt-6 md:-mx-8 md:px-8",
        tabs ? "pb-0" : "pb-5",
        className,
      )}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          {icon ? (
            <span
              aria-hidden="true"
              className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-surface-subtle text-foreground-secondary [&_svg]:size-5"
            >
              {icon}
            </span>
          ) : null}
          <div className="flex min-w-0 flex-col gap-1">
            {aside ? (
              <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
                <h1 className="text-page font-semibold tracking-tight">{title}</h1>
                {aside}
              </div>
            ) : (
              <h1 className="text-page font-semibold tracking-tight">{title}</h1>
            )}
            {/* Text is a paragraph capped at reading width; anything else (the run console's
                facts list) cannot sit in a <p>. */}
            {typeof description === "string" ? (
              <p className="max-w-prose text-meta text-foreground-secondary">{description}</p>
            ) : description ? (
              <div className="text-meta text-foreground-secondary">{description}</div>
            ) : null}
          </div>
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2 md:shrink-0">{actions}</div>
        ) : null}
      </div>
      {tabs ? <div className="-mb-px">{tabs}</div> : null}
    </header>
  );
}
