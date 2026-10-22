import type { RunStatus } from "@/components/status-badge";

import type { StreamStatus } from "./types";

/** How the monitor shows the stream's state: one of the design-system statuses and its wording. */
export function displayStatus(
  stream: StreamStatus,
  waitingAtGate: boolean,
): { status: RunStatus; label: string } {
  switch (stream) {
    case "connecting":
      return { status: "queued", label: "Connecting" };
    case "live":
      return waitingAtGate
        ? { status: "waiting", label: "Needs approval" }
        : { status: "running", label: "Running" };
    case "completed":
      return { status: "succeeded", label: "Succeeded" };
    case "failed":
      return { status: "failed", label: "Failed" };
    case "cancelled":
      return { status: "cancelled", label: "Cancelled" };
    case "not_found":
      return { status: "cancelled", label: "Not found" };
    case "error":
      return { status: "failed", label: "Disconnected" };
  }
}
