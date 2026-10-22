import { CircleAlertIcon, RotateCwIcon, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** A data view with nothing to show: an icon, one sentence and, if there is one, the action. */
export function EmptyState({
  icon: Icon,
  message,
  action,
  className,
}: {
  icon: LucideIcon;
  message: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-dashed px-4 py-8 text-center",
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-6 text-muted-foreground" />
      <p className="text-muted-foreground">{message}</p>
      {action}
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
      <AlertDescription className="flex flex-wrap items-center justify-between gap-2 text-destructive">
        <span role="alert">{message}</span>
        {onRetry ? (
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            <RotateCwIcon aria-hidden="true" data-icon="inline-start" />
            Retry
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
