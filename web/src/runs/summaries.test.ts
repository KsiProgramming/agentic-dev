import { expect, test } from "vitest";

import {
  badgeStatus,
  formatDuration,
  formatRelative,
  isLive,
  repoLabel,
  runTimes,
  wallClockLine,
  statusLabel,
} from "./summaries";
import { runSummary } from "./testing";

test.each([
  [0, "<1s"],
  [999, "<1s"],
  [4_000, "4s"],
  [59_999, "59s"],
  [125_000, "2m 05s"],
  [3_780_000, "1h 03m"],
])("formatDuration(%i) is %s", (ms, text) => {
  expect(formatDuration(ms)).toBe(text);
});

test("formatRelative counts back from now", () => {
  const now = Date.parse("2026-10-22T12:00:00Z");
  expect(formatRelative("2026-10-22T11:59:30Z", now)).toBe("just now");
  expect(formatRelative("2026-10-22T11:55:00Z", now)).toBe("5 min ago");
  expect(formatRelative("2026-10-22T09:00:00Z", now)).toBe("3 h ago");
  expect(formatRelative("2026-10-20T12:00:00Z", now)).toBe("2 d ago");
  expect(formatRelative("2026-09-01T12:00:00Z", now)).toMatch(/2026/);
});

test.each([
  ["https://github.com/acme/docs", "acme/docs"],
  ["https://github.com/acme/docs.git", "acme/docs"],
  ["https://github.com/acme/docs/", "acme/docs"],
  ["/srv/repos/acme/api", "acme/api"],
])("repoLabel(%s) is %s", (url, label) => {
  expect(repoLabel(url)).toBe(label);
});

test("a run that waited 1 h and worked 2 min keeps the two apart", () => {
  const run = runSummary({
    started_at: "2026-10-22T10:00:00Z",
    finished_at: "2026-10-22T11:02:00Z",
    active_ms: 120_000,
    waiting_ms: 3_600_000,
  });
  expect(runTimes(run, Date.parse("2026-10-23T00:00:00Z"))).toEqual({
    activeMs: 120_000,
    waitingMs: 3_600_000,
    wallMs: 3_720_000,
  });
});

test("only the open stretch grows with now", () => {
  const measured = { measured_at: "2026-10-22T10:00:10Z", finished_at: null };
  const now = Date.parse("2026-10-22T10:00:17Z");
  const running = runSummary({ ...measured, status: "running", active_ms: 10_000 });
  expect(runTimes(running, now)).toMatchObject({ activeMs: 17_000, waitingMs: 0 });
  const waiting = runSummary({
    ...measured,
    status: "waiting",
    active_ms: 4_000,
    waiting_ms: 6_000,
  });
  expect(runTimes(waiting, now)).toMatchObject({ activeMs: 4_000, waitingMs: 13_000 });
  const queued = runSummary({ ...measured, status: "queued", started_at: null, active_ms: null });
  expect(runTimes(queued, now)).toEqual({ activeMs: null, waitingMs: 0, wallMs: null });
});

test("the wall clock is a tooltip line", () => {
  expect(wallClockLine(3_720_000, false)).toBe("1h 02m start to end");
  expect(wallClockLine(7_000, true)).toBe("7s start to end so far");
  expect(wallClockLine(null, true)).toBeUndefined();
});

test("statuses map onto the design system", () => {
  expect(badgeStatus("completed")).toBe("succeeded");
  expect(badgeStatus("waiting")).toBe("waiting");
  expect(statusLabel("waiting")).toBe("Needs approval");
  expect(isLive("waiting")).toBe(true);
  expect(isLive("failed")).toBe(false);
});
