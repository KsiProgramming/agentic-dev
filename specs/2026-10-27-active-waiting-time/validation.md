# Validation: Active and waiting time

## Done when (from roadmap)
> A run that waits 1 h at a gate and works for 2 min shows "2m 00s · waited 1 h" in the runs list and the console header

`formatDuration` writes one hour as "1h 00m", so the shown text is "2m 00s · waited 1h 00m".

## Automated checks
- [ ] Store (Testcontainers Postgres): events at started → +1 min `gate_waiting` → +1 h `run_resumed` → +1 min `run_completed` give `active_ms = 120000`, `waiting_ms = 3600000`, both `*_since` null.
- [ ] Store: a crashed attempt counts until its last event and not the gap before `run_resumed`; a run cancelled while waiting closes its waiting stretch at `run_cancelled`; two gates add up.
- [ ] Migration `0020`: upgrade on a database with a waiting run and an ended run; the waiting run's `active_ms` equals the old `active_seconds` result; the ended run has `active_ms = null`; downgrade drops the columns.
- [ ] Worker: the existing wall-time tests pass with `active_seconds` on the projection; a run resumed after a long gate is not stopped for the time it waited.
- [ ] API: `GET /runs` and `GET /runs/{id}` return `active_ms` / `waiting_ms` for ended, running and waiting runs (open stretch included); `duration_ms` is still wall clock and marked `deprecated` in `openapi.json`.
- [ ] Web unit (Vitest): `WaitingTime` ("waiting …" live, "waited …" after, nothing at 0); `runTimes` ticks only the open stretch; runs list cell and card render "2m 00s · waited 1h 00m"; the Started tooltip has the wall clock; timeline builder stretches match the store cases; console header and gate step line.
- [ ] E2E (Playwright): list and header show active time and a "waited" chip for a gate run approved after a few seconds; the routed fixture shows "2m 00s · waited 1h 00m"; `layout.spec.ts` screenshots at 375 / 768 / 1440 and `a11y.spec.ts` (axe) pass.
- [ ] `uv run pytest`, `ruff`, `pyright`; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.

## Manual / demo checks
- [ ] On the dev stack, at 375 and 1440 px, light and dark: the runs list and the console header of a gate run read cleanly; the waiting chip wraps under the duration on a mobile card without horizontal scroll; the tooltips (keyboard focus on the console, hover in the list) show the wall clock.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `openapi.json` and `schema.d.ts` regenerated and committed
- [ ] tech-stack (Display values, run-history contract, decisions log), `CLAUDE.md` rules 3 and 4, and `CHANGELOG.md` updated in the same PR
- [ ] No duration shown in the UI includes waiting time: `duration_ms` appears in `web/src` only in the generated `schema.d.ts` and the `runSummary` test fixture, and `runDurationMs` is gone
