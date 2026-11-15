import { RadioIcon } from "lucide-react";

import { RelativeTime } from "@/components/display";
import { EmptyState } from "@/components/states";

import type { RunDetail } from "../use-run-detail";

/** The step list of a run with no event yet (12.1). A queued run says since when it waits and,
 * once no worker has claimed it past the queue's threshold (`queue_stalled_at`, from the API),
 * that a worker is likely not running. Any other run waits for its first event. */
export function QueuedState({ run, now }: { run: RunDetail | undefined; now: number }) {
  if (run?.status !== "queued") {
    return <EmptyState icon={RadioIcon} message="Waiting for the run to start…" />;
  }
  const stalled = run.queue_stalled_at !== null && now >= new Date(run.queue_stalled_at).getTime();
  return (
    <EmptyState
      icon={RadioIcon}
      message={<RelativeTime iso={run.queued_at} now={now} prefix="Queued " />}
      description={
        stalled
          ? "No worker has picked this run up yet. Check that a worker is running."
          : "Waiting for a worker to pick it up."
      }
    />
  );
}
