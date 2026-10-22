import { expect, test } from "vitest";

import {
  filtersToQuery,
  isFiltered,
  matchesFilters,
  NO_FILTERS,
  parseFilters,
  type RunFilters,
} from "./filters";
import { runSummary } from "./testing";

test("filters round-trip through the URL query", () => {
  const filters: RunFilters = {
    status: ["waiting", "failed"],
    template: "generate-docs",
    repo: "https://github.com/acme/docs",
  };

  const query = filtersToQuery(filters);

  expect(query).toBe(
    "status=waiting&status=failed&template=generate-docs&repo=https%3A%2F%2Fgithub.com%2Facme%2Fdocs",
  );
  expect(parseFilters(new URLSearchParams(query))).toEqual(filters);
});

test("no filters is an empty query", () => {
  expect(filtersToQuery(NO_FILTERS)).toBe("");
  expect(parseFilters(new URLSearchParams(""))).toEqual(NO_FILTERS);
  expect(isFiltered(NO_FILTERS)).toBe(false);
});

test("unknown statuses are dropped and the order is fixed", () => {
  const filters = parseFilters(new URLSearchParams("status=failed&status=done&status=waiting"));

  expect(filters.status).toEqual(["waiting", "failed"]);
});

test("a run matches when every filter matches", () => {
  const run = runSummary({ status: "failed" });

  expect(matchesFilters(run, NO_FILTERS)).toBe(true);
  expect(matchesFilters(run, { ...NO_FILTERS, status: ["failed", "cancelled"] })).toBe(true);
  expect(matchesFilters(run, { ...NO_FILTERS, status: ["waiting"] })).toBe(false);
  expect(matchesFilters(run, { ...NO_FILTERS, template: "audit" })).toBe(false);
  expect(matchesFilters(run, { ...NO_FILTERS, repo: "https://github.com/acme/docs" })).toBe(true);
  expect(matchesFilters({ ...run, repo: null }, { ...NO_FILTERS, repo: "x" })).toBe(false);
});
