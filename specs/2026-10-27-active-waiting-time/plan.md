# Plan: Active and waiting time

Backend first (the projection and the API contract), then the web. The project builds and its tests pass after each group.

## 1. Projection in the `runs` row
- [ ] `packages/store/src/agentic_store/models.py`: `Run.active_ms`, `Run.waiting_ms`, `Run.active_since`, `Run.waiting_since`; document them with the other summary columns.
- [ ] `packages/store/src/agentic_store/sink.py` → `summary_values`: SQL expressions for the stretches (table in the docstring):
  - `run_started`: `active_ms = coalesce(active_ms, 0)`, `active_since = coalesce(active_since, t)`.
  - `gate_waiting`: close the active stretch into `active_ms`, `active_since = null`, `waiting_since = t`.
  - `run_resumed`: close an open waiting stretch at `t`, or a crashed attempt's active stretch at `updated_at` (its last event); `active_since = t`.
  - `run_completed` / `run_failed` / `run_cancelled`: close whichever stretch is open at `t`; both `*_since = null`.
- [ ] `packages/api/alembic/versions/0020_active_waiting_time.py`: add the columns; backfill `queued` / `running` / `waiting` runs from their `run_started`, `run_resumed`, `gate_waiting` and last events (the algorithm of today's `active_seconds`, plus waiting stretches).
- [ ] Store tests (Testcontainers): the 1 h wait + 2 min work run, a crashed attempt, a cancel while waiting, two gates in one run, the migration's backfill against the event-log computation.

## 2. Wall-time limit on the projection
- [ ] `packages/store/src/agentic_store/policy.py` → `active_seconds`: `active_ms` plus `updated_at − active_since` when a stretch is open; drop the window query.
- [ ] Keep the existing worker tests (`test_worker.py` wall-time cases) green; add one for a run resumed after a gate.

## 3. API contract
- [ ] `packages/store/src/agentic_store/summaries.py`: select the four columns into `RunSummaryRow`.
- [ ] `packages/api/src/agentic_api/runs/models.py`: `RunSummary.active_ms: int | None`, `waiting_ms: int` (descriptions say active / waiting, open stretch up to the response); `duration_ms` marked deprecated, described as wall clock.
- [ ] `packages/api/src/agentic_api/runs/routes.py` → `_summary_fields`: add the open stretch up to now (one `now` per response).
- [ ] API tests for `GET /runs` and `GET /runs/{id}`: ended run, running run, waiting run, pre-11.2 ended run (`active_ms: null`).
- [ ] `scripts/export_openapi.py` → `web/openapi.json`, regenerate `web/src/api/schema.d.ts`.

## 4. Display components
- [ ] `web/src/components/display/waiting-time.tsx`: `WaitingTime({ ms, live, focusable })` → "waiting 12 h" / "waited 1m 52s" through `formatDuration`; nothing when `ms` is 0; export from `index.ts`.
- [ ] `RelativeTime`: optional `detail` line added to the tooltip.
- [ ] `web/src/runs/summaries.ts`: `runTimes(run, receivedAt, now)` → `{ activeMs, waitingMs, wallMs }`, ticking the stretch the status names (running → active, waiting → waiting); remove `runDurationMs`.
- [ ] Unit tests in `display.test.tsx` and `summaries.test.ts`.

## 5. Runs list
- [ ] `web/src/runs/runs-list.tsx`: Duration cell = `Duration` (active) + `WaitingTime` in table and card; Started tooltip with the wall clock; `focusable={false}` in rows. The time a page was received comes from the query (`dataUpdatedAt`).
- [ ] Update `web/src/runs/testing.ts` fixtures and the list's unit tests ("2m 00s · waited 1h 00m").

## 6. Console header and gate steps
- [ ] `web/src/runs/timeline.ts`: the builder tracks `activeMs`, `waitingMs` and the open stretch from `run_started`, `run_resumed`, `gate_waiting` and end events, as the sink does.
- [ ] `web/src/runs/console/run-console.tsx` → `headerFacts`: active and waiting from the timeline, the summary's `active_ms` / `waiting_ms` before events; `run-header.tsx` shows `Duration` + `WaitingTime`, wall clock in the Started tooltip.
- [ ] `web/src/runs/console/step-view.tsx` → `TitleLine`: a gate step shows `WaitingTime` (live while waiting) instead of `Duration`.
- [ ] Unit tests: timeline stretches (gate, resume, crash), header facts, gate step line.

## 7. E2E, specs and changelog
- [ ] `web/e2e/runs-page.spec.ts`: a gate run held a few seconds then approved shows active time and a "waited" chip in the list and the header; a routed (`page.route`) summary with `active_ms: 120000`, `waiting_ms: 3600000` shows "2m 00s · waited 1h 00m" in the list. Layout screenshots and axe at 375 / 768 / 1440 updated.
- [ ] `specs/tech-stack.md`: move "Time (11.2)" into Display values and the run-history contract; decisions-log row "Run time projection (11.2)"; wall-time limit bullet points to the projection.
- [ ] `CLAUDE.md`: `WaitingTime` in the rule 3 table; rule 4 without "Until 11.2 ships".
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
