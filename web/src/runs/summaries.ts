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

/** How a run's status is worded: its `statusLabel`, or "Expired" for a run cancelled because
 * its gate waited past its time to live (shown in Cancelled's grey). */
export function runStatusLabel(run: Pick<RunSummary, "status" | "expired">): string {
  return run.expired ? "Expired" : statusLabel(run.status);
}

/** The badge wording of a run whose gate expired ("Expired"); undefined keeps the status's. */
export function expiredLabel(run: Pick<RunSummary, "expired">): string | undefined {
  return run.expired ? "Expired" : undefined;
}

/** Whether the run waits at a gate whose time to live has passed. The worker cancels it within
 * a few seconds; until then it no longer counts as waiting. */
export function gateExpired(run: Pick<RunSummary, "waiting_gate">, now: number): boolean {
  const at = run.waiting_gate?.expires_at;
  return at != null && Date.parse(at) <= now;
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

/** A run's time, kept apart (tech-stack → Display values → Time): `activeMs` is its duration,
 * the time it worked (`null` before it started, or for runs that ended before it was recorded);
 * `waitingMs` the time it was paused at gates; `wallMs` start to end, for a tooltip only. */
export interface RunTimes {
  activeMs: number | null;
  waitingMs: number;
  wallMs: number | null;
}

/** The run's times at `now`: a running run's active time and a waiting run's waiting time keep
 * growing from when the API measured them. */
export function runTimes(run: RunSummary, now: number): RunTimes {
  const since = Math.max(0, now - Date.parse(run.measured_at));
  const end = run.finished_at ? Date.parse(run.finished_at) : now;
  return {
    activeMs: run.active_ms == null ? null : run.active_ms + (run.status === "running" ? since : 0),
    waitingMs: run.waiting_ms + (run.status === "waiting" ? since : 0),
    wallMs: run.started_at ? Math.max(0, end - Date.parse(run.started_at)) : null,
  };
}

/** The wall clock as a tooltip line: "2h 03m start to end" (so far, while live). */
export function wallClockLine(wallMs: number | null, live: boolean): string | undefined {
  if (wallMs === null) return undefined;
  return `${formatDuration(wallMs)} start to end${live ? " so far" : ""}`;
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

/** How long until something runs out at `iso`: `Expires in 2 d`, `Expires in 3 h`,
 * `Expires in 12 min`, `Expires in <1 min`, then `Expired`. Rounded down, so it never promises
 * more time than is left. */
export function formatTimeLeft(iso: string, now: number): string {
  const s = Math.floor((Date.parse(iso) - now) / 1000);
  if (s <= 0) return "Expired";
  const m = Math.floor(s / 60);
  if (m < 1) return "Expires in <1 min";
  if (m < 60) return `Expires in ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `Expires in ${h} h`;
  return `Expires in ${Math.floor(h / 24)} d`;
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
