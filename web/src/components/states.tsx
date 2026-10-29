import { CircleAlertIcon, RotateCwIcon, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** A data view with nothing to show (design-language.md → `EmptyState`): an icon in a tile, one
 * sentence as its title, an optional line under it and, if there is one, the action. */
export function EmptyState({
  icon: Icon,
  message,
  description,
  action,
  className,
}: {
  icon: LucideIcon;
  message: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn("flex flex-col items-center gap-3 px-4 py-10 text-center", className)}
    >
      <span className="flex size-10 items-center justify-center rounded-lg border bg-surface-subtle">
        <Icon aria-hidden="true" className="size-5 text-muted-foreground" />
      </span>
      <div className="flex max-w-prose flex-col gap-1">
        <p className="text-section font-semibold text-foreground">{message}</p>
        {description ? <p className="text-meta text-foreground-secondary">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

/** Skeleton rows while a data view loads. Screen readers hear `label`. */
export function LoadingState({
  rows = 3,
  label = "Loading…",
  className,
}: {
  rows?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div role="status" data-slot="loading-state" className={cn("flex flex-col gap-2", className)}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} aria-hidden="true" className={cn("h-5", i === rows - 1 && "w-2/3")} />
      ))}
    </div>
  );
}

/** A data view that failed to load: the message and, when it can be retried, a Retry button. */
export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: ReactNode;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    // Only the message is announced, not the Retry label: the alert role sits on the message.
    <Alert variant="destructive" role={undefined} data-slot="error-state" className={className}>
      <CircleAlertIcon aria-hidden="true" />
      <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
        <span role="alert">{message}</span>
        {onRetry ? (
          <Button type="button" variant="outline" onClick={onRetry}>
            <RotateCwIcon aria-hidden="true" data-icon="inline-start" />
            Retry
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
