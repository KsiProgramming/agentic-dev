# Plan: POST /runs + GET /runs/{id}/events (SSE)

Contract first: settle the models and the store layer, then the worker, then the HTTP endpoints. The project stays green after each group.

## 1. Contracts and store
- [x] `agentic_api/runs/models.py`: `CreateRunRequest { workflow: WorkflowSpec, input: str = "" }`, `CreateRunResponse { run_id, status, events_url }` (landed with group 3).
- [x] Migration `packages/api/alembic/versions/0003_run_spec.py`: add `runs.spec` (JSONB, not null) and `runs.input` (text, not null, default `''`). Document `queued` in the status values.
- [x] `agentic_store/models.py`: map the new columns.
- [x] `agentic_store/runs.py`: `create_run(sessions, spec, input) -> UUID` (status `queued`) and `get_run(sessions, run_id) -> StoredRun | None` (spec + input + status; also used for the 404 check).
- [x] `PostgresEventSink`: on `run_started`, update the existing row to `running` instead of inserting it. After each insert, `SELECT pg_notify('run_events', :run_id || ':' || :seq)` in the same transaction.
- [x] `agentic_store/notify.py`: `listen(database_url, channel, on_notify, on_lost)` on a dedicated asyncpg connection (one typed wrapper around untyped asyncpg).
- [x] `agentic_store/queue.py`: `RUN_QUEUE = "runs:queue"`, `enqueue_run(redis, run_id)`, `dequeue_run(redis, timeout) -> UUID | None`.
- [x] Update the 0.5 tests that relied on the sink inserting `runs`. Add store tests for `create_run`/`get_run`, the notify and the queue.

## 2. Worker
- [x] New package `packages/worker` (`agentic_worker`, depends on engine + store + runtime). Add it to the workspace sources, ruff `known-first-party` and pyright.
- [x] Move `agentic_engine/worker.py` → `agentic_worker/main.py` (keep settings, ready file and signal handling). Move `test_worker.py` with it.
- [x] `WorkerSettings`: add `database_url` and `fake_step_delay_s: float = 0`.
- [x] Loop: `dequeue_run` → `get_run` → `run_workflow(spec, runtime, input, run_id=..., sink=PostgresEventSink(...))`. Log and continue on a run exception (the sink has already written `run_failed`). On stop, cancel the run in flight (it ends `run_cancelled`). `run()` takes an optional `runtime` for tests.
- [x] `agentic_runtime/fake.py`: helper `slow_echo_script(text, delay)` that splits the reply into `text_delta`s with `Delay`s between them, and `FakeRuntime(default=...)`. The worker builds `FakeRuntime` with it when `fake_step_delay_s > 0`.
- [x] `docker-compose.yml`: worker `command: ["python", "-m", "agentic_worker"]`, `FAKE_STEP_DELAY_S: 0.5`.

## 3. HTTP endpoints
- [x] `agentic_api/runs/routes.py`: `POST /runs` → `create_run` + `enqueue_run`, `202`.
- [x] `agentic_api/runs/listener.py`: `RunEventListener` started in the lifespan. One `LISTEN run_events` connection (reconnects if it drops, then wakes every stream), a map `run_id → set[asyncio.Event]`, and `subscribe(run_id)` as a context manager.
- [x] `GET /runs/{id}/events` (`response_class=EventSourceResponse`): 404 if the run does not exist. Read `Last-Event-ID` / `?after=`. Subscribe **before** the replay query, then loop: `list_run_events(after_seq=last)` → yield `ServerSentEvent(id=str(seq), event=type, data=event)` → stop after a terminal type → otherwise wait on the subscriber event, re-reading every 15 s anyway. Keep-alive `: ping` comments come from FastAPI's SSE support (every 15 s).
- [x] Register the router in `create_app`, and add `sessions` (an `async_sessionmaker`) to `app.state`.

## 4. End-to-end proof and docs
- [x] Integration tests (see validation.md) with Postgres + Redis Testcontainers, the API served by uvicorn on a local port (so the stream is read over real HTTP, like `curl -N`) and the worker loop running as a task in the same event loop.
- [x] README: the `curl` demo (POST a sample spec, then `curl -N` the events URL).
- [x] CHANGELOG entry for 0.6.
