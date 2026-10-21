# Plan: Append-only run_events table; engine writes events

Contract first, then the engine, then Postgres. The project stays green after each group.

## 1. Event envelope and sink contract (engine)
- [ ] `packages/engine/src/agentic_engine/events.py`: `RunEvent` (frozen Pydantic model: `run_id`, `seq`, `type`, `node_id | None`, `payload: dict[str, JsonValue]`, `created_at`) and the lifecycle type names.
- [ ] `EventSink` protocol (`async def emit(self, event: RunEvent) -> None`).
- [ ] `InMemoryEventSink` (keeps a list) for tests; export it from `agentic_engine`.
- [ ] Mypy strict and ruff clean.

## 2. Engine emits events
- [ ] `run_agent_node` forwards each `AgentEvent` to an emit callback as it arrives (not after the stream ends), tagged with the node id.
- [ ] Compiled node wrapper emits `node_started` and the matching `node_completed` / `node_failed` / `node_cancelled`.
- [ ] `run_workflow(spec, runtime, input, *, run_id, sink)`: emits `run_started` and the final `run_*` event, and assigns `seq` from a per-run counter. Default sink keeps current callers working.
- [ ] One test in `tests/test_run_events.py` with `InMemoryEventSink`: the 2-node sequence produces the expected type order with `seq` 1..N.
- [ ] Existing engine tests stay green.

## 3. Store package and migration
- [ ] Add `packages/store` (`agentic_store`) to the `uv` workspace; deps: `sqlalchemy[asyncio]`, `asyncpg`, `agentic-engine`.
- [ ] `agentic_store/models.py`: SQLAlchemy 2.x `Run` and `RunEvent` tables, `metadata`.
- [ ] `packages/api/alembic/versions/0002_run_events.py`: create `runs` and `run_events` (FK, unique `(run_id, seq)`, index on `run_id`), with downgrade.
- [ ] `alembic/env.py`: `target_metadata = agentic_store.metadata`; api depends on `agentic-store`.
- [ ] `agentic_store/sink.py`: `PostgresEventSink(session_factory)` inserts the `runs` row on `run_started`, one `run_events` row per event (committed per event), and updates `runs.status` on the final event.
- [ ] Update `test_migrations.py` to expect `0002_run_events` at head.

## 4. End-to-end proof and docs
- [ ] `packages/store/tests/test_postgres_sink.py` (marked `integration`): migrate a Testcontainers Postgres to head, run the 2-node sequence on the fake runtime with `PostgresEventSink`, read `run_events` back ordered by `seq`.
- [ ] Make sure CI runs the store package's tests (integration job included).
- [ ] README: short section on the event log and the `EventSink` seam. CHANGELOG entry for 0.5.
