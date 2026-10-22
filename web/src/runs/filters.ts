import { API_RUN_STATUSES, type ApiRunStatus, type RunSummary } from "./summaries";

/** What the runs list is narrowed to. Kept in the URL: `?status=failed&status=cancelled&…`. */
export interface RunFilters {
  status: ApiRunStatus[];
  template: string | null;
  repo: string | null;
}

export const NO_FILTERS: RunFilters = { status: [], template: null, repo: null };

/** The templates a run can be filtered by until `GET /templates` answers (or if it fails). */
export const TEMPLATE_OPTIONS = [{ id: "generate-docs", label: "Generate docs" }] as const;

function isStatus(value: string): value is ApiRunStatus {
  return (API_RUN_STATUSES as readonly string[]).includes(value);
}

/** The filters in a URL query. Unknown statuses are dropped; order follows `API_RUN_STATUSES`. */
export function parseFilters(params: URLSearchParams): RunFilters {
  const given = new Set(params.getAll("status").filter(isStatus));
  return {
    status: API_RUN_STATUSES.filter((s) => given.has(s)),
    template: params.get("template") || null,
    repo: params.get("repo") || null,
  };
}

/** The URL query for `filters` (without `?`), empty when nothing is filtered. */
export function filtersToQuery(filters: RunFilters): string {
  const params = new URLSearchParams();
  for (const status of filters.status) params.append("status", status);
  if (filters.template) params.set("template", filters.template);
  if (filters.repo) params.set("repo", filters.repo);
  return params.toString();
}

export function isFiltered(filters: RunFilters): boolean {
  return filters.status.length > 0 || filters.template !== null || filters.repo !== null;
}

/** Whether a list narrowed to `filters` would show `run`. */
export function matchesFilters(run: RunSummary, filters: RunFilters): boolean {
  return (
    (filters.status.length === 0 || filters.status.includes(run.status)) &&
    (filters.template === null || run.template_id === filters.template) &&
    (filters.repo === null || run.repo?.url === filters.repo)
  );
}
