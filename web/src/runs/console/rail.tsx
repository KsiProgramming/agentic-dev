import {
  BanIcon,
  CircleCheckIcon,
  CirclePauseIcon,
  CircleXIcon,
  LoaderCircleIcon,
  type LucideIcon,
} from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

import type { StepStatus } from "../timeline";
import { stepBadge } from "./step-status";

/**
 * A vertical timeline: each entry hangs off one line by its marker (a status icon or a dot), so
 * a run reads top to bottom. Rails nest: a step's entries form a rail inside the step.
 */
export function Rail({ className, ...props }: ComponentProps<"ol">) {
  // `--rail-gap` spaces the entries; each entry's line reaches across it to the next marker.
  return (
    <ol
      className={cn("flex min-w-0 flex-col gap-(--rail-gap) [--rail-gap:--spacing(3)]", className)}
      {...props}
    />
  );
}

/** One entry of a `Rail`. The line runs from its marker down to the next entry's. */
export function RailItem({
  marker,
  markerClassName,
  className,
  children,
  ...props
}: { marker: ReactNode; markerClassName?: string } & ComponentProps<"li">) {
  return (
    // The last entry has no line below it; `>` keeps nested rails' lines out of this rule.
    <li
      className={cn("relative min-w-0 pl-7 [&:last-child>[data-rail-line]]:hidden", className)}
      {...props}
    >
      <span
        aria-hidden="true"
        data-rail-line=""
        className="absolute top-5.5 bottom-[calc(var(--rail-gap)*-1)] left-[9px] w-px bg-border"
      />
      <span
        className={cn(
          "absolute top-0 left-0 flex size-5 items-center justify-center bg-background",
          markerClassName,
        )}
      >
        {marker}
      </span>
      {children}
    </li>
  );
}

const STATUS_ICON: Record<StepStatus, { icon: LucideIcon; className: string }> = {
  running: { icon: LoaderCircleIcon, className: "text-status-running motion-safe:animate-spin" },
  waiting: { icon: CirclePauseIcon, className: "text-status-waiting" },
  completed: { icon: CircleCheckIcon, className: "text-status-succeeded" },
  failed: { icon: CircleXIcon, className: "text-status-failed" },
  cancelled: { icon: BanIcon, className: "text-status-cancelled" },
};

/** A step's or map item's status as the marker: an icon, with its label for screen readers
 * (status is never colour alone). */
export function StatusMarker({ status, small = false }: { status: StepStatus; small?: boolean }) {
  const { icon: Icon, className } = STATUS_ICON[status];
  return (
    <>
      <Icon aria-hidden="true" className={cn(small ? "size-3.5" : "size-4", className)} />
      <span className="sr-only">{stepBadge(status).label}</span>
    </>
  );
}

/** A quiet dot, for an entry whose status says nothing (a message). */
export function DotMarker({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("size-1.5 rounded-full bg-muted-foreground/50", className)}
    />
  );
}

/** An icon marker, e.g. the loop icon of an iteration. */
export function IconMarker({ icon: Icon, className }: { icon: LucideIcon; className?: string }) {
  return <Icon aria-hidden="true" className={cn("size-3.5 text-muted-foreground", className)} />;
}
