"use client";

import { LoaderCircleIcon } from "lucide-react";

import type { Activity } from "./activity";

/** The live line at the end of a running run's timeline: where it is and what it is doing. */
export function ActivityLine({ activity }: { activity: Activity }) {
  return (
    <div
      data-testid="activity"
      className="relative flex min-h-5 min-w-0 items-center gap-1.5 pl-7 text-meta text-muted-foreground"
    >
      <span className="absolute top-0 left-0 flex size-5 items-center justify-center">
        <LoaderCircleIcon
          aria-hidden="true"
          className="size-4 text-status-running motion-safe:animate-spin"
        />
      </span>
      <span className="shrink-0 font-mono text-foreground">{activity.where}</span>
      <span className="shrink-0">·</span>
      <span className="min-w-0 truncate">
        {activity.doing}
        {activity.target ? (
          <>
            {" "}
            <span className="font-mono text-foreground">{activity.target}</span>
          </>
        ) : null}
        …
      </span>
      {activity.running > 1 ? (
        <span className="ml-auto shrink-0 text-caption tabular-nums">
          {activity.running} running
        </span>
      ) : null}
    </div>
  );
}
