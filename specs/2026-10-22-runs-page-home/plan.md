# Plan: Runs page (new home)

Order: data layer first, then UI, then live updates (user choice). After each group the app still builds and the existing pages work.

## 1. Data layer: TanStack Query + summaries client
- [ ] Add `@tanstack/react-query` to `web/package.json`. Add `web/src/components/query-provider.tsx` (a client component holding one `QueryClient`) and wrap it around the shell in `web/src/app/layout.tsx`.
- [ ] Add typed helpers in `web/src/api/client.ts` for `listRuns` (`GET /runs`, with repeatable `status`, `template`, `repo`, `cursor`, `limit`) and `getRun`, using the generated schema types.
- [ ] Add `web/src/runs/use-run-summaries.ts`: `useRunSummaries(filters)` as a `useInfiniteQuery` over `next_cursor`, with the key `["runs", workspaceId, filters]`. Add `useWaitingRuns()` for the "Needs approval" section.
- [ ] Add `web/src/runs/format.ts`: `formatDuration(ms)`, a live duration from `started_at`, a relative "started" time, and `repoLabel(url)` → `owner/name`.
- [ ] Add Vitest tests for the helpers and hooks (with fetch mocked).

## 2. Runs list UI: table, cards, states
- [ ] Add `web/src/runs/runs-table.tsx` (≥ 768 px), built on `components/ui/table`, 13 px, mono for the repo, `tabular-nums` for the times. Rows link to `/runs/{id}`, and the PR link is a separate focusable link.
- [ ] Add `web/src/runs/run-card.tsx` (< 768 px) with the same fields, using `components/ui/card`.
- [ ] Add `web/src/runs/runs-list.tsx`: picks the table or cards with CSS (`hidden md:block` and the reverse), and shows skeleton, empty, error/Retry and "Load more" from `components/states`.
- [ ] Replace the placeholder in `web/src/app/runs/page.tsx`: `PageHeader` with a "New run" action that links to `/templates`, the "Needs approval" section (only if it has runs), and "All runs".
- [ ] Add component tests: one row and one card per status, PR link present or absent, waiting runs on top, each of the states.

## 3. Filters in the URL
- [ ] Add `web/src/runs/run-filters.tsx`: a status multi-select (dropdown with checkboxes), a template select and a repo select (from `GET /workspaces/{id}/repos`, hidden when GitHub is not connected), plus "Clear filters". On mobile the filters stack below the header.
- [ ] Add `web/src/runs/filters.ts`: parse and serialise `?status=…&template=…&repo=…` to and from `RunFilters`, and sync them with `useSearchParams` and `router.replace`.
- [ ] Add the "No runs match these filters" empty state.
- [ ] Add tests: a URL round-trip, a filter change updates the query key, and "Clear filters" resets everything.

## 4. Live updates: `GET /runs/stream`
- [ ] Backend, in `packages/api/src/agentic_api/runs/listener.py`: add `subscribe_workspace()`, which yields an event plus a set of notified run ids. `notify()` adds the run id to every workspace subscriber's set and wakes it. `_wake_all()` marks those subscribers "refresh all".
- [ ] Backend, in `packages/api/src/agentic_api/runs/routes.py`: add `GET /runs/stream?workspace_id` (`operation_id="streamRunSummaries"`), declared before `/{run_id}`. On a wake-up it loads `get_run_summary` for each notified run, keeps the ones in the workspace, and sends a `run_summary` frame when the summary differs from the last one sent. It sends a `: keep-alive` comment every 15 s. Add the OpenAPI SSE description like `_SSE_RUN_EVENTS`.
- [ ] Backend tests in `packages/api/tests/` (Testcontainers Postgres): a status change produces one frame, unchanged deltas produce none, other workspaces are filtered out, and a listener reconnect re-sends current summaries.
- [ ] Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`.
- [ ] Frontend, in `web/src/runs/use-runs-stream.ts`: one `EventSource` per page. On `run_summary` it patches the item in all `["runs", …]` caches with `setQueryData`. It invalidates the list queries when the run is unknown or when its status crossed into or out of `waiting`. On `open` (and so on every reconnect) it invalidates the lists. It closes on unmount.
- [ ] Add an `aria-live="polite"` announcer, for example "Run Generate docs is now Succeeded", and the live-ticking duration for `running` rows.
- [ ] Add tests with a fake `EventSource`: cache patching, invalidation rules and cleanup.

## 5. E2E and cleanup
- [ ] Add `web/e2e/runs-page.spec.ts`, using `web/e2e/runs.ts` helpers: start a succeeded run, a failed run and a gated run through the API (a fake runtime agent that fails, plus `GATE`).
- [ ] Remove the "coming soon" copy and update any e2e (`home.spec.ts`, `layout.spec.ts`) that relied on the placeholder.
- [ ] Mark roadmap 2.4 done in the implementation PR (`complete-phase` skill).
