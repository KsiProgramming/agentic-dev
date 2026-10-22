import type { RunStatus } from "@/components/status-badge";

import type { StepStatus } from "../timeline";

const BADGE: Record<StepStatus, { status: RunStatus; label: string }> = {
  running: { status: "running", label: "Running" },
  waiting: { status: "waiting", label: "Needs approval" },
  completed: { status: "succeeded", label: "Done" },
  failed: { status: "failed", label: "Failed" },
  cancelled: { status: "cancelled", label: "Cancelled" },
};

/** How a step, map item or tool call shows its status: a design-system status and its wording. */
export function stepBadge(status: StepStatus): { status: RunStatus; label: string } {
  return BADGE[status];
}
