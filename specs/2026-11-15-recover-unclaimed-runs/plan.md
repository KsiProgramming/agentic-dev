# Plan: Recover runs lost before a worker claims them

Test first: each group starts with the test that fails today, and the project stays green after each group.

## 1. Reproduce both gaps
- [x] `packages/worker/tests/test_worker.py`: `test_run_popped_by_a_dead_worker_still_starts`: create a run, `dequeue_run` its id and drop it (a worker killed before it claimed), start a worker with small `queue_stale_s` / `queue_sweep_s`, and assert the run reaches `completed`. Marked `xfail(strict=True)` until group 3.
- [x] `test_unloadable_spec_fails_the_run_and_the_worker_goes_on`: write a run whose stored spec has an unknown field (as an older worker would see `budget_usd`), queue it and a good run after it; assert the bad run ends `failed` with the reason and the good one `completed`. Also covers a reclaimed run (expired lease) with the same spec. `xfail(strict=True)` until group 3.

## 2. Store: queue timestamps and the sweep
- [x] Alembic `0029_run_queue_times`: `runs.queued_at` and `runs.enqueued_at` (timestamptz, nullable), backfilled from `created_at` for `queued` runs; a partial index on `queued_at` where `status = 'queued' AND lease_expires_at IS NULL`.
- [x] `agentic_store.models.Run`: the two columns, and the docstring explains them.
- [x] `queued_at` defaults to `now()` (creation, rerun) and is set wherever a run becomes `queued` again: `approvals` (decision), `cancel` (while waiting), `expiry.expire_gates`. Only the sweep writes `enqueued_at`.
- [x] `agentic_store.queue.requeue_stale_runs(sessions, redis, stale_s) -> list[UUID]`: lock the stale rows `SKIP LOCKED`, set `enqueued_at = now()`, commit, then `enqueue_run` each one. Export it from `agentic_store`.
- [x] `agentic_store.lease`: `_claimed` returns the raw row and no longer parses inside the transaction. A new `load_claimed(row) -> StoredRun | UnloadableRun` parses after the commit and returns the error text and the raw spec's `id`/`name` on failure.
- [x] `packages/store/tests/test_queue.py`: `requeue_stale_runs` picks only `queued`, lease-less runs past both thresholds; skips fresh, leased, `running`, `waiting` and ended runs; two concurrent sweeps push each id once; a run pushed again keeps its `queued_at`.
- [x] `packages/store/tests`: a claim of a run with an unparseable spec commits the lease and returns the unloadable result instead of raising.

## 3. Worker: the sweep and the failure path
- [x] `WorkerSettings`: `queue_stale_s` (default 60, env `QUEUE_STALE_S`) and `queue_sweep_s` (default 15, env `QUEUE_SWEEP_S`), both `gt=0`.
- [x] `_sweep_queue(worker, redis)` beside `_sweep_gates`: runs once at start, then every `queue_sweep_s`, logs each id it pushes again, and an error is logged without stopping the worker. Started in `run()` next to the gate sweep.
- [x] `_next_run`: an unloadable claim or reclaim goes to `_fail_unloadable(worker, row, error)`, which writes `run_started` (raw `id`/`name`) and `run_failed` with `failure_reason = "this worker cannot load the run's spec: <error>"` (or only `run_failed` after its last event if it had started), then releases it. The loop goes on.
- [x] Engine: `record_unstarted_run` accepts a workflow id and name instead of a parsed spec (or a sibling helper), so a run with no parsed spec can still be logged.
- [x] The group 1 tests pass (written against the finished worker rather than marked `xfail` first).

## 4. API and console
- [x] `packages/api` settings: `queue_stale_s` from the same `QUEUE_STALE_S` env var.
- [x] `agentic_store.summaries` and `agentic_api.runs.models`: `queued_at: datetime` and `queue_stalled_at: datetime | None` on the run summary and detail. API tests for a fresh and a stalled queued run.
- [x] `web/src/runs`: the API types gain the two fields. `run-console.tsx`'s queued empty state shows "Queued" with `RelativeTime` (from `queued_at`) and, once past `queue_stalled_at`, the hint as its one sentence. Update `run-console.test.tsx` for both states.
- [x] Check at 375 and 1440 px, light and dark.

## 5. Specs and docs
- [x] `specs/tech-stack.md`: the queue and lease rules (Postgres is the source of truth, the queue sweep, the two settings, the unloadable-spec failure) next to the expiry rules in "Run history and rerun"; `queued_at` / `queue_stalled` in the run summary contract; the console's queued state in "Run console"; a decisions-log row "Queue recovery (12.1)".
- [x] `specs/ideas.md`: the idea's open questions answered (the worker sweeps; 60 s threshold; the version check left open).
- [x] `.env.example` and `docs/operations/deployment.md`: `QUEUE_STALE_S`, `QUEUE_SWEEP_S`.
- [x] `CHANGELOG.md` under `[Unreleased]`.
