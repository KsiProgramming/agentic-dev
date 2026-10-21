# Plan: Durable execution with the Postgres checkpointer

The work is engine first, with the saver injected. Each group leaves `main` working: until group 4 the worker still runs without a checkpointer.

## 1. Engine: checkpointer and resume (no database)
- [ ] `agentic_engine/graph/compile.py`: `compile_workflow(..., checkpointer: BaseCheckpointSaver | None = None)` passes it to `builder.compile(checkpointer=...)`.
- [ ] `agentic_engine/events.py`: `RunEventLog(run_id, sink, start_seq=0)`, plus a `RUN_RESUMED = "run_resumed"` event type. `RUN_END_STATUS` is unchanged.
- [ ] `agentic_engine/graph/run.py`:
  - `run_workflow(..., checkpointer=None)` calls `ainvoke` with `{"configurable": {"thread_id": str(run_id)}}` when a checkpointer is given.
  - Factor the result summary (`_summarise(final)`) out of `run_workflow`.
- [ ] `resume_workflow(spec, runtime, *, run_id, checkpointer, sink, next_seq, attempt)`:
  - It reads the checkpoint (`aget_state`) and emits `run_resumed` with `{attempt, completed_nodes}`.
  - Then it calls `ainvoke(None, config)` and ends with the same `run_<status>` handling as `run_workflow`.
  - If no checkpoint exists, it starts from the input. A run that died before its first checkpoint behaves like a fresh start with `run_resumed`.
- [ ] Export `resume_workflow` and `RUN_RESUMED` from `agentic_engine.graph` and `agentic_engine.events`.
- [ ] `packages/engine/tests/test_resume.py` (see validation.md). Settle the `AgentNodeResult` serialization question here. If the serializer refuses the model, change `RunState.results` to hold dumped dicts and validate them on read.

## 2. Schema: lease columns and checkpoint tables
- [ ] `packages/api/alembic/versions/0005_run_lease.py`: add `runs.worker_id TEXT NULL`, `runs.lease_expires_at TIMESTAMPTZ NULL`, `runs.attempt INT NOT NULL DEFAULT 0`, and a partial index on `lease_expires_at WHERE status IN ('queued','running')`.
- [ ] `packages/api/alembic/versions/0006_checkpoints.py`:
  - `upgrade` opens a sync psycopg connection (autocommit) from the Alembic URL and runs `PostgresSaver(conn).setup()`.
  - `downgrade` drops `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations`.
- [ ] `agentic_store/models.py`: add the three new `Run` columns, and update the docstring on lease semantics.
- [ ] The existing `test_migrations.py` covers upgrade and downgrade to head.

## 3. Store: checkpointer factory, seq and lease functions
- [ ] `packages/store/pyproject.toml`: add `langgraph-checkpoint-postgres` and `psycopg[binary,pool]`, then run `uv lock`.
- [ ] `agentic_store/checkpoint.py`: `open_checkpointer(database_url)` is an async context manager that yields an `AsyncPostgresSaver` backed by an `AsyncConnectionPool`. It turns `postgresql+asyncpg://` into `postgresql://`.
- [ ] `agentic_store/sink.py`: `max_event_seq(sessions, run_id) -> int`.
- [ ] `agentic_store/lease.py`:
  - `claim_run(run_id, worker_id, ttl)` atomically sets owner, expiry and `attempt + 1`, only if the run is `queued` with no live lease. It returns the run or `None`.
  - `renew_lease(run_id, worker_id, ttl) -> bool` returns `False` if the lease was lost.
  - `release_run(run_id, worker_id)` clears the owner and expiry.
  - `reclaim_expired_run(worker_id, ttl)` picks one `queued` or `running` run with `lease_expires_at < now()`, using `FOR UPDATE SKIP LOCKED`, and claims it.
- [ ] `agentic_store/queue.py`: update the module docstring. Redis now only signals new runs, and lost jobs come back through reclaim.

## 4. Worker: claim, heartbeat, reclaim, resume
- [ ] `WorkerSettings`: `worker_id` (default `<hostname>-<pid>`), `lease_ttl_s=30`, `lease_heartbeat_s=10`, `max_attempts=3`.
- [ ] `run()`:
  - Open `open_checkpointer(settings.database_url)` once per worker.
  - In the loop, check `reclaim_expired_run` first, then `dequeue_run` + `claim_run`.
  - Do one reclaim pass at startup, before the ready file is touched.
- [ ] `process_run`:
  - Run a heartbeat task next to the run, calling `renew_lease` every `lease_heartbeat_s`.
  - If the lease is lost, cancel the run without writing an end event, because another worker owns it now.
  - Release the lease in `finally`.
- [ ] A fresh claim (`attempt == 1`) uses `run_workflow(..., checkpointer=...)`. A reclaim (`attempt > 1`) uses `resume_workflow(..., next_seq=max_event_seq + 1, attempt=...)`. Past `max_attempts`, emit `run_failed` with `{"error": "gave up after N attempts"}`.
- [ ] `_until_stopped`: on `stop`, cancel the run task as a drain. The engine must not emit `run_cancelled` in that case:
  - Pass a `drain` flag, or catch it in the worker and skip the end event.
  - Then release the lease, so another worker picks the run up straight away.
- [ ] Sandbox:
  - Before `sandboxes.open` on a reclaimed run, remove any leftover container for that run id (new `SandboxManager.discard(run_id)`; a no-op for the fake backend).
  - In `build_sandboxes`, replace the blanket `sweep_orphans` with a sweep limited to runs that are not `running` with a live lease. Pass a predicate or the set of live run ids.
- [ ] Update the module docstrings in `main.py`, which still say "not resumed after a restart yet".

## 5. Demo fixture and docs
- [ ] `packages/engine/tests/fixtures/specs/valid/three-step-sequence.json`: three agent nodes (`step-1`, `step-2`, `step-3`). The existing fixture tests pick it up.
- [ ] `docker-compose.yml`: no new service. Optionally expose `LEASE_TTL_S` to the worker so the demo can shorten it.
- [ ] README: a "Durable runs (phase 1.3)" section with the kill/restart steps from validation.md.
- [ ] CHANGELOG entry.
- [ ] Tick this plan and mark phase 1.3 done (`complete-phase` skill) on the implementation PR.
