# Plan: Runs page (new home)

Order: data layer first, then UI, then live updates (user choice). After each group the app still builds and the existing pages work.

## 1. Data layer: TanStack Query + summaries client
- [x] Add `@tanstack/react-query` to `web/package.json`. Add `web/src/components/query-provider.tsx` (a client component holding one `QueryClient`) and wrap it around the shell in `web/src/app/layout.tsx`.
- [x] Add typed helpers in `web/src/api/client.ts` for `listRuns` (`GET /runs`, with repeatable `status`, `template`, `repo`, `cursor`, `limit`) and `getRun`, using the generated schema types.
- [x] Add `web/src/runs/use-run-summaries.ts`: `useRunList(filters)` as a `useInfiniteQuery` over `next_cursor`, with the key `["runs", workspaceId, "list", filters, limit]`. The "Needs approval" section is the same hook with `status: ["waiting"]`.
- [x] Add `web/src/runs/summaries.ts`: `formatDuration(ms)`, a live duration from `started_at`, a relative "started" time, and `repoLabel(url)` → `owner/name`.
- [x] Add Vitest tests for the helpers and hooks (with fetch mocked).

## 2. Runs list UI: table, cards, states
- [x] Add `web/src/runs/runs-table.tsx` (≥ 768 px), built on `components/ui/table`, 13 px, mono for the repo, `tabular-nums` for the times. Rows link to `/runs/{id}`, and the PR link is a separate focusable link.
- [x] Add `web/src/runs/run-card.tsx` (< 768 px) with the same fields, using `components/ui/card`.
- [x] Add `web/src/runs/runs-list.tsx`: picks the table or cards with CSS (`hidden md:block` and the reverse), and shows skeleton, empty, error/Retry and "Load more" from `components/states`.
- [x] Replace the placeholder in `web/src/app/runs/page.tsx`: `PageHeader` with a "New run" action that links to `/templates`, the "Needs approval" section (only if it has runs), and "All runs".
- [x] Add component tests: one row and one card per status, PR link present or absent, waiting runs on top, each of the states.

## 3. Filters in the URL
- [x] Add `web/src/runs/run-filters.tsx`: a status multi-select (dropdown with checkboxes), a template select and a repo select (from `GET /workspaces/{id}/repos`, hidden when GitHub is not connected), plus "Clear filters". On mobile the filters stack below the header.
- [x] Add `web/src/runs/filters.ts`: parse and serialise `?status=…&template=…&repo=…` to and from `RunFilters`, and sync them with `useSearchParams` and `router.replace`.
- [x] Add the "No runs match these filters" empty state.
- [x] Add tests: a URL round-trip, a filter change updates the query key, and "Clear filters" resets everything.

## 4. Live updates: `GET /runs/stream`
- [x] Backend, in `packages/api/src/agentic_api/runs/listener.py`: add `subscribe_all()`, an event set on every notification and on a listener reconnect.
- [x] Backend, in `packages/store/src/agentic_store/summaries.py`: add `list_changed_run_summaries(workspace_id, since)`, the runs whose `updated_at` is after `since`.
- [x] Backend, in `packages/api/src/agentic_api/runs/routes.py`: add `GET /runs/stream?workspace_id` (`operation_id="streamRunSummaries"`), declared before `/{run_id}`, with the workspace check as a dependency. On each wake-up or 15 s recheck it reads the changes since its watermark minus a 5 s lookback, and sends a `run_summary` frame when a summary differs from the last one sent. Add the OpenAPI SSE description (`_sse_of("RunSummary")`).
- [x] Backend tests in `packages/api/tests/test_runs.py` (Testcontainers Postgres): gated run waiting → completed, deltas send nothing, other workspaces filtered, recheck without a notification, unknown workspace 404.
- [x] Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`.
- [x] Frontend, in `web/src/runs/use-runs-stream.ts`: one `EventSource` per page. `applySummary` patches each cached list that shows the run and still matches, and refetches a list the run joins or leaves. Every reconnect after the first refetches the lists. It closes on unmount.
- [x] Add an `aria-live="polite"` announcer ("Run Generate docs is now Succeeded.") and the live-ticking duration (`useNow`).
- [x] Add tests with a fake `EventSource`: cache patching, refetch rules, reconnect and cleanup.

## 5. E2E and cleanup
- [x] Add `web/e2e/runs-page.spec.ts`, using `web/e2e/runs.ts` helpers: start a succeeded run, a failed run and a gated run through the API (a fake runtime agent that fails, plus `GATE`).
- [x] Remove the "coming soon" copy and update any e2e (`home.spec.ts`, `layout.spec.ts`) that relied on the placeholder.
- [ ] Mark roadmap 2.4 done in the implementation PR (`complete-phase` skill).
