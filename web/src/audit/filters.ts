import { AUDIT_CATEGORIES, actionsOf, type AuditAction, type AuditCategory } from "./actions";

/** What the audit log is narrowed to. Kept in the URL: `?category=runs&run=<id>&from=…&to=…`.
 * `from` and `to` are local dates (`YYYY-MM-DD`), both included. */
export interface AuditFilters {
  category: AuditCategory | null;
  run: string | null;
  from: string | null;
  to: string | null;
}

export const NO_AUDIT_FILTERS: AuditFilters = { category: null, run: null, from: null, to: null };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isRunId(value: string): boolean {
  return UUID.test(value);
}

function isCategory(value: string | null): value is AuditCategory {
  return AUDIT_CATEGORIES.some((c) => c.id === value);
}

function date(value: string | null): string | null {
  return value && DATE.test(value) && !Number.isNaN(Date.parse(value)) ? value : null;
}

/** The filters in a URL query; values that are not valid are dropped. */
export function parseAuditFilters(params: URLSearchParams): AuditFilters {
  const category = params.get("category");
  const run = params.get("run")?.trim().toLowerCase() ?? null;
  return {
    category: isCategory(category) ? category : null,
    run: run && isRunId(run) ? run : null,
    from: date(params.get("from")),
    to: date(params.get("to")),
  };
}

/** The URL query for `filters` (without `?`), empty when nothing is filtered. */
export function auditFiltersToQuery(filters: AuditFilters): string {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.run) params.set("run", filters.run);
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  return params.toString();
}

export function isAuditFiltered(filters: AuditFilters): boolean {
  return Object.values(filters).some((v) => v !== null);
}

/** Local midnight of a `YYYY-MM-DD` date, `days` later. */
function midnight(day: string, days = 0): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return new Date(y, m - 1, d + days).toISOString();
}

/** The query of `GET /workspaces/{id}/audit` for `filters`: `to` includes its whole day. */
export function auditQuery(filters: AuditFilters): {
  action?: AuditAction[];
  run_id?: string;
  since?: string;
  until?: string;
} {
  return {
    ...(filters.category ? { action: actionsOf(filters.category) } : {}),
    ...(filters.run ? { run_id: filters.run } : {}),
    ...(filters.from ? { since: midnight(filters.from) } : {}),
    ...(filters.to ? { until: midnight(filters.to, 1) } : {}),
  };
}
