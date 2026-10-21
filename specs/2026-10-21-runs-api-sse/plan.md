# Plan: POST /runs + GET /runs/{id}/events (SSE)

Contract first: settle the models and the store layer, then the worker, then the HTTP endpoints. The project stays green after each group.

## 1. Contracts and store
- [ ] `agentic_api/runs/models.py`: `CreateRunRequest { workflow: WorkflowSpec, input: str = "" }`, `CreateRunResponse { run_id, status, events_url }`.
- [ ] Migration `packages/api/alembic/versions/0003_run_spec.py`: add `runs.spec` (JSONB, not null) and `runs.input` (text, not null, default `''`). Document `queued` in the status values.
- [ ] `agentic_store/models.py`: map the new columns.
- [ ] `agentic_store/runs.py`: `create_run(sessions, spec, input) -> UUID` (status `queued`), `load_run(sessions, run_id)` (spec + input + status) and `run_exists`.
- [ ] `PostgresEventSink`: on `run_started`, update the existing row to `running` instead of inserting it. After each insert, `SELECT pg_notify('run_events', :run_id || ':' || :seq)` in the same transaction.
- [ ] `agentic_store/queue.py`: `RUN_QUEUE = "runs:queue"`, `enqueue_run(redis, run_id)`, `dequeue_run(redis, timeout) -> UUID | None`.
- [ ] Update the 0.5 tests that relied on the sink inserting `runs`. Add store tests for `create_run`/`load_run` and for the notify.

## 2. Worker
- [ ] New package `packages/worker` (`agentic_worker`, depends on engine + store + runtime). Add it to the workspace sources, ruff `known-first-party` and pyright.
- [ ] Move `agentic_engine/worker.py` → `agentic_worker/main.py` (keep settings, ready file and signal handling). Move `test_worker.py` with it.
- [ ] `WorkerSettings`: add `database_url` and `fake_step_delay_s: float = 0`.
- [ ] Loop: `dequeue_run` → `load_run` → `run_workflow(spec, runtime, input, run_id=..., sink=PostgresEventSink(...))`. Log and continue on a run exception (the sink has already written `run_failed`). Stop cleanly on the stop event.
- [ ] `agentic_runtime/fake.py`: helper `slow_echo_script(text, delay)` that splits the reply into `text_delta`s with `Delay`s between them. The worker builds `FakeRuntime` with it when `fake_step_delay_s > 0`.
- [ ] `docker-compose.yml`: worker `command: ["python", "-m", "agentic_worker"]`, `FAKE_STEP_DELAY_S: 0.5`.

## 3. HTTP endpoints
- [ ] `agentic_api/runs/routes.py`: `POST /runs` → `create_run` + `enqueue_run`, `202`.
- [ ] `agentic_api/runs/listener.py`: `RunEventListener` started in the lifespan. One raw asyncpg connection `LISTEN run_events`, a map `run_id → set[asyncio.Event]`, and `subscribe(run_id)` as an async context manager.
- [ ] `GET /runs/{id}/events` (`response_class=EventSourceResponse`): 404 if the run does not exist. Read `Last-Event-ID` / `?after=`. Subscribe **before** the replay query, then loop: `list_run_events(after_seq=last)` → yield `ServerSentEvent(id=str(seq), event=type, data=event)` → stop after a terminal type → otherwise wait on the subscriber event with a 15 s timeout (on timeout send `ServerSentEvent(comment="keep-alive")`).
- [ ] Register the router in `create_app`, and add `sessions` (an `async_sessionmaker`) to `app.state`.

## 4. End-to-end proof and docs
- [ ] Integration tests (see validation.md) with Postgres + Redis Testcontainers, the API app via `httpx.ASGITransport` and the worker loop running as a task in the same event loop.
- [ ] README: the `curl` demo (POST a sample spec, then `curl -N` the events URL).
- [ ] CHANGELOG entry for 0.6.
