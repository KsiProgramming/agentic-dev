import type { components } from "@/api/schema";

import { PROVIDER_NAMES, type ProviderName } from "./provider-label";
import { API_RUN_STATUSES, type ApiRunStatus, type RunSummary } from "./summaries";

/** What a runs list is narrowed to, as `GET /runs` takes it. */
export interface RunFilters {
  status: ApiRunStatus[];
  template: string | null;
  repo: string | null;
  /** Only runs where any agent ran on this provider (8.3). */
  provider: ProviderName | null;
}

export const NO_FILTERS: RunFilters = { status: [], template: null, repo: null, provider: null };

/** The templates a run can be filtered by until `GET /templates` answers (or if it fails). */
export const TEMPLATE_OPTIONS = [{ id: "generate-docs", label: "Generate docs" }] as const;

/** The runs list's saved views, shown as tabs. Each counts its runs in `GET /runs/counts`. */
export const RUN_VIEWS = [
  { id: "all", label: "All", status: [] },
  { id: "running", label: "Running", status: ["running", "queued"] },
  { id: "waiting", label: "Needs approval", status: ["waiting"] },
  { id: "failed", label: "Failed", status: ["failed"] },
] as const satisfies readonly {
  id: keyof components["schemas"]["RunCounts"];
  label: string;
  status: readonly ApiRunStatus[];
}[];

export type RunViewId = (typeof RUN_VIEWS)[number]["id"];

/** The runs page's state, kept in the URL: `?view=failed&template=…&repo=…`. */
export interface RunsQuery {
  view: RunViewId;
  template: string | null;
  repo: string | null;
  provider: ProviderName | null;
}

export const ALL_RUNS: RunsQuery = { view: "all", template: null, repo: null, provider: null };

function isProvider(value: string | null): value is ProviderName {
  return value !== null && value in PROVIDER_NAMES;
}

function isView(value: string | null): value is RunViewId {
  return RUN_VIEWS.some((v) => v.id === value);
}

/** The runs page's state in a URL query. An unknown view is All. */
export function parseRunsQuery(params: URLSearchParams): RunsQuery {
  const view = params.get("view");
  return {
    view: isView(view) ? view : "all",
    template: params.get("template") || null,
    repo: params.get("repo") || null,
    provider: ((p) => (isProvider(p) ? p : null))(params.get("provider")),
  };
}

/** The URL query for `query` (without `?`), empty for All with no filter. */
export function runsQueryToString(query: RunsQuery): string {
  const params = new URLSearchParams();
  if (query.view !== "all") params.set("view", query.view);
  if (query.template) params.set("template", query.template);
  if (query.repo) params.set("repo", query.repo);
  if (query.provider) params.set("provider", query.provider);
  return params.toString();
}

/** Whether a template, repo or provider narrows the list (the view is not a filter). */
export function isFiltered(query: Pick<RunsQuery, "template" | "repo" | "provider">): boolean {
  return query.template !== null || query.repo !== null || query.provider !== null;
}

/** What `GET /runs` is asked for to show `query`. */
export function viewFilters(query: RunsQuery): RunFilters {
  const view = RUN_VIEWS.find((v) => v.id === query.view) ?? RUN_VIEWS[0];
  return {
    status: API_RUN_STATUSES.filter((s) => (view.status as readonly string[]).includes(s)),
    template: query.template,
    repo: query.repo,
    provider: query.provider,
  };
}

/** Whether a list narrowed to `filters` would show `run`. */
export function matchesFilters(run: RunSummary, filters: RunFilters): boolean {
  return (
    (filters.status.length === 0 || filters.status.includes(run.status)) &&
    (filters.template === null || run.template_id === filters.template) &&
    (filters.repo === null || run.repo?.url === filters.repo) &&
    (filters.provider === null || run.providers.includes(filters.provider))
  );
}
