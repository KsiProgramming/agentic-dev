import { dateFormat } from "@/lib/locale";

import type { RunSummary } from "./summaries";

/** The date headers the runs list groups its rows under, newest first. */
export type DateGroup = "Today" | "Yesterday" | "This week" | "Earlier";

const DAY_MS = 86_400_000;

/** The calendar day of `ms` in the display time zone, as a day number. */
function day(ms: number): number {
  const parts = dateFormat({ year: "numeric", month: "numeric", day: "numeric" }).formatToParts(ms);
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return Date.UTC(part("year"), part("month") - 1, part("day")) / DAY_MS;
}

/** Which header a moment falls under at `now`: Today, Yesterday, This week (the 7 days up to
 * today), else Earlier. Calendar days in the display time zone. */
export function dateGroup(iso: string, now: number): DateGroup {
  const ago = day(now) - day(Date.parse(iso));
  if (ago <= 0) return "Today";
  if (ago === 1) return "Yesterday";
  if (ago < 7) return "This week";
  return "Earlier";
}

/** Runs, newest first, cut into consecutive groups by when they were created. */
export function groupRuns(
  runs: RunSummary[],
  now: number,
): { group: DateGroup; runs: RunSummary[] }[] {
  const groups: { group: DateGroup; runs: RunSummary[] }[] = [];
  for (const run of runs) {
    const group = dateGroup(run.created_at, now);
    const last = groups.at(-1);
    if (last?.group === group) last.runs.push(run);
    else groups.push({ group, runs: [run] });
  }
  return groups;
}
