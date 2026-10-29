import * as React from "react";
import { cn } from "cn";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-md border border-border-strong bg-background px-2.5 py-2 text-base transition-colors outline-none placeholder:text-placeholder focus-visible:border-ring focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:bg-muted disabled:opacity-50 aria-invalid:border-status-failed aria-invalid:ring-1 aria-invalid:ring-status-failed md:text-meta",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
