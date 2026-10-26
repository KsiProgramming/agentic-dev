import { expect, test } from "vitest";

import {
  auditFiltersToQuery,
  auditQuery,
  isAuditFiltered,
  NO_AUDIT_FILTERS,
  parseAuditFilters,
  type AuditFilters,
} from "./filters";

const RUN = "1a2b3c4d-0000-4000-8000-000000000001";

test("filters round-trip through the URL query", () => {
  const filters: AuditFilters = {
    category: "approvals",
    run: RUN,
    from: "2026-10-01",
    to: "2026-10-26",
  };

  const query = auditFiltersToQuery(filters);

  expect(query).toBe(`category=approvals&run=${RUN}&from=2026-10-01&to=2026-10-26`);
  expect(parseAuditFilters(new URLSearchParams(query))).toEqual(filters);
  expect(isAuditFiltered(filters)).toBe(true);
});

test("no filters is an empty query, and invalid values are dropped", () => {
  expect(auditFiltersToQuery(NO_AUDIT_FILTERS)).toBe("");
  expect(isAuditFiltered(NO_AUDIT_FILTERS)).toBe(false);
  expect(
    parseAuditFilters(
      new URLSearchParams("category=secrets&run=1a2b&from=yesterday&to=2026-13-45"),
    ),
  ).toEqual(NO_AUDIT_FILTERS);
});

test("the API query takes the category's actions and whole local days", () => {
  const query = auditQuery({
    category: "approvals",
    run: RUN,
    from: "2026-10-01",
    to: "2026-10-02",
  });

  expect(query.action).toEqual(["gate.approved", "gate.rejected"]);
  expect(query.run_id).toBe(RUN);
  expect(query.since).toBe(new Date(2026, 9, 1).toISOString());
  expect(query.until).toBe(new Date(2026, 9, 3).toISOString());
  expect(auditQuery(NO_AUDIT_FILTERS)).toEqual({});
});
