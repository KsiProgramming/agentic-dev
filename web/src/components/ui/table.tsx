"use client";

import * as React from "react";
import { cn } from "cn";

/** A table sits in a bordered card with an 8 px radius (design-language.md → Surfaces); pass
 * `bordered={false}` when it is already inside one. `scrollLabel` names the container as a
 * focusable region, so a table wider than the screen can be scrolled from the keyboard (axe
 * `scrollable-region-focusable`). `containerClassName` styles that container (a table whose
 * sticky rows follow the page drops its overflow where it fits). */
function Table({
  className,
  scrollLabel,
  containerClassName,
  bordered = true,
  ...props
}: React.ComponentProps<"table"> & {
  scrollLabel?: string;
  containerClassName?: string;
  bordered?: boolean;
}) {
  return (
    <div
      data-slot="table-container"
      className={cn(
        "relative w-full overflow-x-auto",
        bordered && "rounded-lg border bg-card",
        containerClassName,
      )}
      {...(scrollLabel ? { role: "region", "aria-label": scrollLabel, tabIndex: 0 } : {})}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-meta", className)}
        {...props}
      />
    </div>
  );
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  // The header row is tinted and never hovers.
  return (
    <thead
      data-slot="table-header"
      className={cn(
        "bg-surface-subtle [&_tr]:border-b [&_tr]:border-border [&_tr]:hover:bg-transparent",
        className,
      )}
      {...props}
    />
  );
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("border-t bg-surface-subtle font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  );
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-divider transition-colors hover:bg-muted has-aria-expanded:bg-muted data-[state=selected]:bg-surface-subtle",
        className,
      )}
      {...props}
    />
  );
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-row-header px-3 text-left align-middle text-caption font-medium whitespace-nowrap text-muted-foreground [&:has([role=checkbox])]:pr-0",
        className,
      )}
      {...props}
    />
  );
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "h-row px-3 py-1 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0",
        className,
      )}
      {...props}
    />
  );
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-meta text-muted-foreground", className)}
      {...props}
    />
  );
}

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption };
