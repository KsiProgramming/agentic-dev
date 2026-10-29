import * as React from "react";
import { cn } from "cn";

/**
 * A keyboard hint (design-language.md → Components): 11 px, a 1 px border, radius 4 px, in
 * `muted-foreground`; on a primary button (`onPrimary`) in its foreground with a faint border.
 */
function Kbd({
  className,
  onPrimary = false,
  ...props
}: React.ComponentProps<"kbd"> & { onPrimary?: boolean }) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex items-center rounded-sm border px-1 font-sans text-kbd font-medium",
        onPrimary
          ? "border-primary-foreground/30 text-primary-foreground"
          : "border-border text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Kbd };
