import { describe, expect, test } from "vitest";

import { breadcrumbsFor, isActive } from "./nav";

describe("isActive", () => {
  test.each([
    ["/runs", "/runs", true],
    ["/runs/1a2b", "/runs", true],
    ["/runsx", "/runs", false],
    ["/settings", "/runs", false],
  ])("%s under %s is %s", (pathname, href, expected) => {
    expect(isActive(pathname, href)).toBe(expected);
  });
});

describe("breadcrumbsFor", () => {
  test("a section page is the only crumb", () => {
    expect(breadcrumbsFor("/settings")).toEqual([{ label: "Settings" }]);
    expect(breadcrumbsFor("/audit")).toEqual([{ label: "Audit log" }]);
    expect(breadcrumbsFor("/inbox")).toEqual([{ label: "Inbox" }]);
  });

  test("a run links back to Runs and shortens its id", () => {
    const id = "1a2b3c4d-0000-0000-0000-000000000000";
    expect(breadcrumbsFor(`/runs/${id}`)).toEqual([
      { label: "Runs", href: "/runs" },
      { label: "1a2b3c4d", title: id, mono: true },
    ]);
  });

  test("a settings sub-page is named, not shown as an id", () => {
    expect(breadcrumbsFor("/settings/integrations")).toEqual([
      { label: "Settings", href: "/settings" },
      { label: "Integrations" },
    ]);
    expect(breadcrumbsFor("/settings/limits")[1]).toEqual({ label: "Limits and budgets" });
  });

  test("a short segment is kept whole", () => {
    expect(breadcrumbsFor("/runs/abc")[1]).toEqual({ label: "abc", title: undefined, mono: true });
  });

  test("a path outside the sections has none", () => {
    expect(breadcrumbsFor("/")).toEqual([]);
  });
});
