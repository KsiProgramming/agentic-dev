import { expect, test } from "vitest";

import {
  ALL_RUNS,
  isFiltered,
  matchesFilters,
  NO_FILTERS,
  parseRunsQuery,
  runsQueryToString,
  viewFilters,
  type RunsQuery,
} from "./filters";
import { runSummary } from "./testing";

test("the view and filters round-trip through the URL query", () => {
  const query: RunsQuery = {
    view: "failed",
    template: "generate-docs",
    repo: "https://github.com/acme/docs",
  };

  const search = runsQueryToString(query);

  expect(search).toBe(
    "view=failed&template=generate-docs&repo=https%3A%2F%2Fgithub.com%2Facme%2Fdocs",
  );
  expect(parseRunsQuery(new URLSearchParams(search))).toEqual(query);
});

test("All with no filter is an empty query; an unknown view is All", () => {
  expect(runsQueryToString(ALL_RUNS)).toBe("");
  expect(parseRunsQuery(new URLSearchParams(""))).toEqual(ALL_RUNS);
  expect(parseRunsQuery(new URLSearchParams("view=done")).view).toBe("all");
  expect(isFiltered(ALL_RUNS)).toBe(false);
  // The view picks the status; it is not a filter to clear.
  const failed: RunsQuery = { ...ALL_RUNS, view: "failed" };
  expect(isFiltered(failed)).toBe(false);
});

test("each view asks the API for its statuses", () => {
  const statuses = (view: RunsQuery["view"]) => viewFilters({ ...ALL_RUNS, view }).status;

  expect(statuses("all")).toEqual([]);
  expect(statuses("running")).toEqual(["running", "queued"]);
  expect(statuses("waiting")).toEqual(["waiting"]);
  expect(statuses("failed")).toEqual(["failed"]);
  expect(viewFilters({ view: "all", template: "t", repo: "r" })).toEqual({
    status: [],
    template: "t",
    repo: "r",
  });
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
