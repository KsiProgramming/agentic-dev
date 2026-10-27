import type { components } from "@/api/schema";
import type { RunStatus } from "@/components/status-badge";
import { dateFormat } from "@/lib/locale";

/** A run as `GET /runs` and `GET /runs/stream` describe it. */
export type RunSummary = components["schemas"]["RunSummary"];
export type RunSummaryPage = components["schemas"]["RunSummaryPage"];
/** A run status as the API spells it. */
export type ApiRunStatus = components["schemas"]["RunStatus"];

/** The API's run statuses in the order filters list them. */
export const API_RUN_STATUSES: readonly ApiRunStatus[] = [
  "waiting",
  "running",
  "queued",
  "completed",
  "failed",
  "cancelled",
];

const BADGE_STATUS: Record<ApiRunStatus, RunStatus> = {
  queued: "queued",
  running: "running",
  waiting: "waiting",
  completed: "succeeded",
  failed: "failed",
  cancelled: "cancelled",
};

/** The design-system status of an API run status (`completed` shows as Succeeded). */
export function badgeStatus(status: ApiRunStatus): RunStatus {
  return BADGE_STATUS[status];
}

/** How the runs list words a status: a waiting run needs the user. */
export function statusLabel(status: ApiRunStatus): string {
  return STATUS_LABEL[status];
}

const STATUS_LABEL: Record<ApiRunStatus, string> = {
  queued: "Queued",
  running: "Running",
  waiting: "Needs approval",
  completed: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Whether the run may still change by itself (its duration is still growing). */
export function isLive(status: ApiRunStatus): boolean {
  return status === "queued" || status === "running" || status === "waiting";
}

/** How long the run took, or has taken so far if it is still going; `null` before it started. */
export function runDurationMs(run: RunSummary, now: number): number | null {
  if (run.duration_ms != null) return run.duration_ms;
  if (!run.started_at) return null;
  const end = run.finished_at ? Date.parse(run.finished_at) : now;
  return Math.max(0, end - Date.parse(run.started_at));
}

const pad = (n: number) => String(n).padStart(2, "0");

/** `850 ms` → `<1s`, `4 s`, `2m 05s`, `1h 03m`. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return "<1s";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${pad(s % 60)}s`;
  return `${Math.floor(m / 60)}h ${pad(m % 60)}m`;
}

/** When something happened, relative to `now`: `just now`, `5 min ago`, `3 h ago`, `2 d ago`,
 * then the date. */
export function formatRelative(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d} d ago`;
  return dateFormat({ day: "numeric", month: "short", year: "numeric" }).format(Date.parse(iso));
}

/** The full date and time, for a tooltip. */
export function formatAbsolute(iso: string): string {
  return dateFormat({ dateStyle: "medium", timeStyle: "medium" }).format(Date.parse(iso));
}

/** The time of day to the second, for a log line. */
export function formatClock(iso: string): string {
  return dateFormat({ timeStyle: "medium" }).format(Date.parse(iso));
}

/** `https://github.com/acme/docs(.git)` → `acme/docs`; a local path → its last two segments. */
export function repoLabel(url: string): string {
  const path = url
    .replace(/^[a-z]+:\/\/[^/]+\//i, "")
    .replace(/\.git$/, "")
    .replace(/\/+$/, "");
  return path.split("/").filter(Boolean).slice(-2).join("/") || url;
}
