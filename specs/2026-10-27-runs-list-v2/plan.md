# Plan: Runs list v2

## 1. API contract: trigger, branch, counts, workspaces
- [ ] Alembic `0022_runs_trigger_branch`: `runs.trigger` (not null, backfilled) and `runs.branch` (backfilled from `repo->>'ref'`, then from `repo_created` events)
- [ ] `agentic_store`: `RunRow.trigger` / `branch`; `create_run(trigger=…)`; the sink sets `branch` on `repo_created` when unset; `count_runs(…)`; `create_workspace(name)`
- [ ] `agentic_api.runs`: `CreateRunRequest.trigger`, `RunSummary.trigger` / `branch`, `GET /runs/counts` (`RunCounts`), rerun stores `rerun`
- [ ] `agentic_api.workspaces`: `POST /workspaces`
- [ ] pytest: migration, sink, counts (expired gate excluded, filters), trigger on create and rerun, workspace creation
- [ ] Regenerate `openapi.json` and `web/src/api/schema.d.ts`

## 2. Test runs in their own workspace
- [ ] `web/src/workspace.ts`: `WORKSPACE_COOKIE`, `useWorkspaceId()`; replace each hard-coded default (runs, rerun, attention, settings, templates, audit)
- [ ] `web/e2e`: global setup finds or creates "E2E" and connects Claude and GitHub there; `startRun` and the other API calls pass `workspace_id`; Playwright sets the cookie for every page
- [ ] `scripts/sandbox_demo.py`: a "Demo" workspace

## 3. Runs list v2 (web)
- [ ] `src/runs/filters.ts`: views (`all`, `running`, `waiting`, `failed`) mapped to status filters; URL parse and serialise (`view`, `template`, `repo`); drop the status dropdown from `RunFiltersBar`
- [ ] `use-run-counts.ts`: `GET /runs/counts`, under the runs query key so the stream refreshes it
- [ ] `run-views.tsx`: tabs with counts (links with `aria-current`)
- [ ] `date-groups.ts`: Today / Yesterday / This week / Earlier in the display time zone (`@/lib/locale`)
- [ ] `runs-list.tsx`: Run column (name, `IdChip`, trigger), Repository with its branch, a waiting row's status badge as its review link, sticky date headers in the table and the cards
- [ ] `runs-view.tsx`: no pinned section; one list for the chosen view; per-view empty states
- [ ] The New run sheet sends `trigger: "manual"`
- [ ] Vitest for views, groups, list and view

## 4. e2e and specs
- [ ] `runs-page.spec.ts`: real runs come first while one waits; the Needs approval tab is one click; the default workspace has no run from the suite
- [ ] Update other e2e specs that relied on the pinned section or the Review button; layout and axe pass
- [ ] tech-stack: "Runs list" rules moved from UI v2; run history contract (`trigger`, `branch`, counts, `POST /workspaces`); `CHANGELOG.md`
