import { expect, test } from "vitest";

import {
  badgeStatus,
  formatDuration,
  formatRelative,
  isLive,
  repoLabel,
  runDurationMs,
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

test("a finished run's duration is the API's", () => {
  expect(runDurationMs(runSummary(), 0)).toBe(125_000);
});

test("a live run's duration grows with now; before it starts there is none", () => {
  const running = runSummary({ status: "running", finished_at: null, duration_ms: null });
  const now = Date.parse("2026-10-22T10:00:07Z");
  expect(runDurationMs(running, now)).toBe(7_000);
  expect(runDurationMs({ ...running, status: "queued", started_at: null }, now)).toBeNull();
});

test("statuses map onto the design system", () => {
  expect(badgeStatus("completed")).toBe("succeeded");
  expect(badgeStatus("waiting")).toBe("waiting");
  expect(statusLabel("waiting")).toBe("Needs approval");
  expect(isLive("waiting")).toBe(true);
  expect(isLive("failed")).toBe(false);
});
