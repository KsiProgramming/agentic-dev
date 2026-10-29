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

/** Colour means status only, and status is always icon + label, never colour alone. Each pill has
 * its status's fill, text and edge (design-language.md → Components). Class names are written out
 * in full so Tailwind sees them. */
const STATUS: Record<RunStatus, { label: string; icon: LucideIcon; className: string }> = {
  queued: {
    label: "Queued",
    icon: ClockIcon,
    className: "border-status-queued-border bg-status-queued-muted text-status-queued",
  },
  running: {
    label: "Running",
    icon: LoaderCircleIcon,
    className:
      "border-status-running-border bg-status-running-muted text-status-running [&>svg]:motion-safe:animate-spin",
  },
  waiting: {
    label: "Waiting",
    icon: CirclePauseIcon,
    className: "border-status-waiting-border bg-status-waiting-muted text-status-waiting",
  },
  succeeded: {
    label: "Succeeded",
    icon: CircleCheckIcon,
    className: "border-status-succeeded-border bg-status-succeeded-muted text-status-succeeded",
  },
  failed: {
    label: "Failed",
    icon: CircleXIcon,
    className: "border-status-failed-border bg-status-failed-muted text-status-failed",
  },
  cancelled: {
    label: "Cancelled",
    icon: BanIcon,
    className: "border-status-cancelled-border bg-status-cancelled-muted text-status-cancelled",
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
    <Badge data-status={status} className={cn(tone, className)} {...props}>
      <Icon aria-hidden="true" data-icon="inline-start" />
      {label ?? fallback}
    </Badge>
  );
}
