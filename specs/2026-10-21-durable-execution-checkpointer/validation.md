# Validation: Durable execution with the Postgres checkpointer

## Done when (from roadmap)
> Killing a worker mid-run and restarting it resumes after the last completed node (AC-8)

To check this: start a run of `three-step-sequence.json` on the slow fake runtime. Kill the worker (SIGKILL) after `step-1` has completed and while `step-2` is running, then start a worker again. Within the lease TTL, the run's event log shows `run_resumed` (`completed_nodes: ["step-1"]`), then `step-2` and `step-3`, then `run_completed`. `step-1` has exactly one `node_completed` and is not started again. `seq` has no gaps and no duplicates.

The proof chosen for this phase:
- the engine resume unit tests, run automatically;
- the manual compose demo below.

## Automated checks
- [ ] `packages/engine/tests/test_resume.py` uses `InMemorySaver` and `FakeRuntime`, with no network or database:
  - [ ] `test_resume_skips_completed_nodes`:
    - Run the 3-node spec with a fake script that blocks in `step-2`, and cancel the task while it is blocked (simulated crash).
    - `resume_workflow` with a new runtime instance runs only `step-2` and `step-3`. The `step-1` script is called exactly once over both attempts.
    - The final `order` is `[step-1, step-2, step-3]` and `last_text` comes from `step-3`.
  - [ ] `test_resume_events_continue_seq`:
    - The resumed attempt's first event is `run_resumed` with `attempt` and `completed_nodes == ["step-1"]`. Its `seq` is `next_seq`.
    - The events after it have contiguous `seq`, and the run ends with `run_completed`.
  - [ ] `test_resume_without_checkpoint_starts_fresh`: a run that died before its first checkpoint resumes from the input and runs every node.
  - [ ] `test_resume_after_failed_node_keeps_failure`: a run whose last checkpoint ended on a failed node resumes to `run_failed` with the same `stopped_at`. It does not run the failed node again.
  - [ ] `test_checkpoint_round_trips_node_results`: `AgentNodeResult` (with usage) survives the saver's serializer unchanged.
  - [ ] `test_run_workflow_without_checkpointer_unchanged`: existing behaviour and event sequence stay the same when no checkpointer is passed.
- [ ] Existing suites stay green, with no new database dependency for the engine:
  - `packages/engine/tests/test_no_database.py`;
  - `test_run_workflow.py` and `test_run_events.py`;
  - `packages/worker/tests/test_worker.py`;
  - `packages/api/tests/test_migrations.py`, which now upgrades through 0006 and downgrades back.
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict) and `uv run pytest` pass locally and in CI.

## Manual / demo checks
Compose demo for AC-8 (also in the README):
- [ ] `FAKE_STEP_DELAY_S=2 docker compose up -d --build`. The migrations run, and the checkpoint tables exist (`docker compose exec postgres psql -U agentic -c '\dt checkpoint*'`).
- [ ] `curl -s -X POST localhost:8000/runs -H 'content-type: application/json' -d "{\"workflow\": $(cat packages/engine/tests/fixtures/specs/valid/three-step-sequence.json), \"input\": \"hello\"}"`. Note the `run_id`.
- [ ] Open `http://localhost:3000/runs/<run_id>` (or `curl -N localhost:8000/runs/<run_id>/events`). Wait for `node_completed step-1` and `node_started step-2`.
- [ ] `docker compose kill worker`. The run stays `running` and no end event appears.
- [ ] `docker compose up -d worker`. Within about 30 s (lease TTL), the stream shows:
  - `run_resumed` (`attempt: 2`, `completed_nodes: ["step-1"]`);
  - then `node_started step-2`, `step-3` and `run_completed`.
- [ ] `curl -s localhost:8000/runs/<run_id>/events` (or a `psql` query on `run_events`):
  - `step-1` has exactly one `node_started` and one `node_completed`;
  - `seq` runs from 1 to N with no gaps or duplicates.
- [ ] Graceful drain: repeat with `docker compose stop worker` in place of `kill`, then `up -d worker`. No `run_cancelled` is written and the run resumes the same way.
- [ ] Sandbox: repeat with a run that has a `repo` (`ask-repo.json` with `/samples/agentic-dev.git`). After the restart, `docker ps -a --filter label=<sandbox label>` shows one container for the run, the fresh one, and the run completes.
- [ ] Crash loop: with `MAX_ATTEMPTS=1`, kill the worker mid-run and restart it. The run ends `run_failed` with "gave up after 1 attempts" and is not retried.

## Merge criteria
- [ ] All automated checks above pass in CI (`ci.yml`, `pr-checks.yml`), including the roadmap check.
- [ ] The manual compose demo has been run once, and its event output is pasted into the PR description.
- [ ] `alembic upgrade head` on an existing dev database (with runs from earlier phases) succeeds. Old runs have `attempt = 0` and no lease, and are never reclaimed.
- [ ] No secrets in logs. The psycopg connection string is never logged, because `open_checkpointer` logs only host and database.
- [ ] Docstrings that said "durable execution comes later" are updated (`queue.py`, `worker/main.py`). README and CHANGELOG are updated.
- [ ] `plan.md` is ticked and roadmap phase 1.3 is marked done in the implementation PR.
