# Plan: Append-only run_events table; engine writes events

Contract first, then the engine, then Postgres. The project stays green after each group.

## 1. Event envelope and sink contract (engine)
- [x] `packages/engine/src/agentic_engine/events.py`: `RunEvent` (frozen Pydantic model: `run_id`, `seq`, `type`, `node_id | None`, `payload: dict[str, JsonValue]`, `created_at`) and the lifecycle type names.
- [x] `EventSink` protocol (`async def emit(self, event: RunEvent) -> None`).
- [x] `InMemoryEventSink` (keeps a list) for tests, plus `NullEventSink` and the `RunEventLog` numberer, all in `agentic_engine.events`.
- [x] Mypy strict and ruff clean.

## 2. Engine emits events
- [x] `run_agent_node` forwards each `AgentEvent` to an emit callback as it arrives (not after the stream ends), tagged with the node id.
- [x] Compiled node wrapper emits `node_started` and the matching `node_completed` / `node_failed` / `node_cancelled`.
- [x] `run_workflow(spec, runtime, input, *, run_id, sink)`: emits `run_started` and the final `run_*` event, and assigns `seq` from a per-run counter. Default sink keeps current callers working.
- [x] `tests/test_run_events.py` with `InMemoryEventSink`: the 2-node sequence produces the expected type order with `seq` 1..N; a failed node and caller cancellation end with `run_failed` / `run_cancelled`.
- [x] Existing engine tests stay green.

## 3. Store package and migration
- [x] Add `packages/store` (`agentic_store`) to the `uv` workspace; deps: `sqlalchemy[asyncio]`, `asyncpg`, `agentic-engine`.
- [x] `agentic_store/models.py`: SQLAlchemy 2.x `Run` and `RunEvent` tables, `metadata`.
- [x] `packages/api/alembic/versions/0002_run_events.py`: create `runs` and `run_events` (FK without cascade, unique `(run_id, seq)`, which also serves lookups by `run_id`), with downgrade.
- [x] `alembic/env.py`: `target_metadata = agentic_store.metadata`; api depends on `agentic-store`.
- [x] `agentic_store/sink.py`: `PostgresEventSink(session_factory)` inserts the `runs` row on `run_started`, one `run_events` row per event (committed per event), and updates `runs.status` on the final event.
- [x] Update `test_migrations.py` to expect `0002_run_events` at head and run `alembic check` (models match migrations).
- [x] Copy the store package's `pyproject.toml` in the API Dockerfile.

## 4. End-to-end proof and docs
- [x] `packages/store/tests/test_postgres_sink.py` (marked `integration`): migrate a Testcontainers Postgres to head, run the 2-node sequence on the fake runtime with `PostgresEventSink`, read `run_events` back ordered by `seq`.
- [x] Make sure CI runs the store package's tests (the `python` job's `uv run pytest` already covers `packages/*`, integration included).
- [x] `packages/engine/tests/test_no_database.py`: importing the engine loads no SQLAlchemy or asyncpg.
- [x] README: short section on the event log and the `EventSink` seam. CHANGELOG entry for 0.5.
