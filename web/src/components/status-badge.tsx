import {
  BanIcon,
  CircleCheckIcon,
  CirclePauseIcon,
  CircleXIcon,
  ClockIcon,
  LoaderCircleIcon,
  type LucideIcon,
} from "lucide-react";
import type { ComponentProps } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export const RUN_STATUSES = [
  "queued",
  "running",
  "waiting",
  "succeeded",
  "failed",
  "cancelled",
] as const;

export type RunStatus = (typeof RUN_STATUSES)[number];

/** Colour means status only, and status is always icon + label, never colour alone. Class names
 * are written out in full so Tailwind sees them. */
const STATUS: Record<RunStatus, { label: string; icon: LucideIcon; className: string }> = {
  queued: {
    label: "Queued",
    icon: ClockIcon,
    className: "bg-status-queued-muted text-status-queued",
  },
  running: {
    label: "Running",
    icon: LoaderCircleIcon,
    className: "bg-status-running-muted text-status-running [&>svg]:motion-safe:animate-spin",
  },
  waiting: {
    label: "Waiting",
    icon: CirclePauseIcon,
    className: "bg-status-waiting-muted text-status-waiting",
  },
  succeeded: {
    label: "Succeeded",
    icon: CircleCheckIcon,
    className: "bg-status-succeeded-muted text-status-succeeded",
  },
  failed: {
    label: "Failed",
    icon: CircleXIcon,
    className: "bg-status-failed-muted text-status-failed",
  },
  cancelled: {
    label: "Cancelled",
    icon: BanIcon,
    className: "bg-status-cancelled-muted text-status-cancelled",
  },
};

/** A run or node status as a badge. `label` replaces the default wording, not the colour. */
export function StatusBadge({
  status,
  label,
  className,
  ...props
}: {
  status: RunStatus;
  label?: string;
  className?: string;
} & Omit<ComponentProps<"span">, "children">) {
  const { label: fallback, icon: Icon, className: tone } = STATUS[status];
  return (
    <Badge data-status={status} className={cn("h-6 px-2 text-xs", tone, className)} {...props}>
      <Icon aria-hidden="true" data-icon="inline-start" />
      {label ?? fallback}
    </Badge>
  );
}
