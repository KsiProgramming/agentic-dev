import { afterEach, expect, test } from "vitest";

import { formatCount, formatPrice, formatUsd } from "@/runs/cost";
import { formatAbsolute, formatClock, formatRelative } from "@/runs/summaries";

import { displayLocale, pinDisplayLocale } from "./locale";

const EN = { locale: "en-US", timeZone: "UTC" };

afterEach(() => pinDisplayLocale(EN));

test("dates follow the display time zone", () => {
  pinDisplayLocale({ locale: "en-US", timeZone: "Asia/Tokyo" });
  expect(formatClock("2026-10-22T12:00:00Z")).toBe("9:00:00 PM");
});

test("a 24-hour locale shows 24-hour times and its own date order", () => {
  pinDisplayLocale({ locale: "de-DE", timeZone: "Europe/Berlin" });
  expect(formatClock("2026-10-22T12:00:00Z")).toBe("14:00:00");
  expect(formatAbsolute("2026-10-22T12:00:00Z")).toBe("22.10.2026, 14:00:00");
  expect(formatRelative("2026-01-05T12:00:00Z", Date.parse("2026-10-22T12:00:00Z"))).toBe(
    "5. Jan. 2026",
  );
});

/** ICU puts a no-break space between an amount and its symbol. */
const spaced = (text: string) => text.replace(/ /g, " ");

test("numbers and amounts use the locale's separators, always in dollars", () => {
  pinDisplayLocale({ locale: "de-DE", timeZone: "Europe/Berlin" });
  expect(formatCount(12345)).toBe("12.345");
  expect(spaced(formatUsd(1234.5))).toBe("1.234,50 $");
  expect(spaced(formatUsd(0.0423))).toBe("0,0423 $");
  expect(spaced(formatUsd(0.0001))).toBe("<0,001 $");
  expect(spaced(formatPrice(3))).toBe("3,00 $");
});

test("unpinned, the browser's locale and time zone are used", () => {
  pinDisplayLocale(null);
  const { locale, timeZone } = new Intl.DateTimeFormat().resolvedOptions();
  expect(displayLocale()).toEqual({ locale, timeZone });
});
