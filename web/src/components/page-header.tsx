import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A page's title, a short description and its primary actions: on the right from `md`,
 * stacked under the title below that. Breadcrumbs live in the top bar. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      data-slot="page-header"
      className={cn("flex flex-col gap-3 md:flex-row md:items-start md:justify-between", className)}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-page font-semibold tracking-tight">{title}</h1>
        {/* Text is a paragraph capped at reading width; anything else (the run console's facts
            list) cannot sit in a <p>. */}
        {typeof description === "string" ? (
          <p className="max-w-prose text-muted-foreground">{description}</p>
        ) : description ? (
          <div className="text-muted-foreground">{description}</div>
        ) : null}
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center gap-2 md:shrink-0">{actions}</div>
      ) : null}
    </header>
  );
}
