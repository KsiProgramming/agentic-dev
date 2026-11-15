# Validation: Recover runs lost before a worker claims them

## Done when (from roadmap)
> A run whose id was popped from Redis by a worker killed before it claimed the run still starts within the threshold; a run with a spec the worker cannot parse fails with a clear reason and the worker keeps serving other runs

"Within the threshold" is checked as at most `QUEUE_STALE_S + QUEUE_SWEEP_S` plus one poll (75 s with the defaults). The tests use small values.

## Automated checks

### Worker integration (Testcontainers Postgres and Redis)
- [ ] `test_run_popped_by_a_dead_worker_still_starts`: an id taken from Redis and dropped; a worker started afterwards runs the run to `completed` within the bound.
- [ ] The same with the worker already running when the id is dropped (the timer sweep, not only the one at start).
- [ ] `test_unloadable_spec_fails_the_run_and_the_worker_goes_on`: the bad run ends `failed` with `failure_reason` starting "this worker cannot load the run's spec:"; its events are `run_started` then `run_failed`; the good run queued after it completes on the same worker.
- [ ] A reclaimed run (expired lease, had events) with an unparseable spec gets only `run_failed` after its last event, and no worker stops.
- [ ] Two workers sweeping at once: each lost run is claimed and run exactly once (`attempt = 1`).
- [ ] A run queued again after a gate decision and then lost is swept and resumes from its checkpoint.

### Store unit
- [ ] `requeue_stale_runs` picks only `queued` runs with no lease, `queued_at` and `enqueued_at` past the threshold.
- [ ] It skips fresh, leased, `running`, `waiting`, `completed`, `failed` and `cancelled` runs.
- [ ] It sets `enqueued_at`, leaves `queued_at` alone, and a second sweep within the threshold pushes nothing.
- [ ] A claim of an unparseable spec commits the lease and returns the error, without raising.
- [ ] The migration upgrades and downgrades; queued runs are backfilled.

### API
- [ ] `GET /runs/{id}` and `GET /runs` return `queued_at` and `queue_stalled` (`false` when fresh, `true` past `QUEUE_STALE_S`, `false` once running).

### Repo checks
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest` for `store`, `worker`, `api` and `engine`.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test` (the console's queued and stalled states in `run-console.test.tsx`).
- [ ] `pnpm test:e2e` passes as before (no new spec; CLAUDE.md requires it for a UI change).

## Manual / demo checks
- [ ] `docker compose up`, then stop the worker (`docker compose stop worker`). Start a docs run from the web. Run `docker compose exec redis redis-cli RPOP runs:queue` to drop its id. The console shows "Queued … ago", and after 60 s the hint.
- [ ] `docker compose start worker`: the run starts within about 75 s and the worker log names the id it pushed again.
- [ ] Set a queued run's spec to one with an unknown field (`psql`: `UPDATE runs SET spec = spec || '{"unknown": 1}' …`), queue it, and queue a normal run after it. The first ends `failed` with the reason in the console's failure banner; the second completes; the worker container never restarts.
- [ ] The console's queued state looks right at 375 and 1440 px, in light and dark.

## Merge criteria
- [ ] Every check above passes locally (CI minutes are limited; CI runs on the PR).
- [ ] `tech-stack.md` (queue rules, run summary contract, run console, decisions log), `ideas.md`, `.env.example` and the deployment doc updated in the same PR.
- [ ] `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] No secrets in the new log lines (only run ids and the parse error).
- [ ] Not needed: a real Claude run (lessons.md rule 1). The phase does not change what any agent receives.
