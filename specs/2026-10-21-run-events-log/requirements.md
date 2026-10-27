# Append-only run_events table; engine writes events

Roadmap phase: 0.5
Branch: plan/0.5-run-events-log

## Context
Phase 0.4 runs a `sequence` of `agent` nodes end to end on the fake runtime, but everything a run does lives only in memory (`AgentNodeResult.events`). The mission's **Transparency** principle says every agent action, tool call and cost is kept in an append-only log, and the tech stack makes the `run_events` table in Postgres the single source for the monitor, cost view and audit.

This phase adds that log. It depends on 0.1 (Postgres, Alembic, Testcontainers), 0.3 (`AgentEvent`) and 0.4 (`run_workflow`), all done. It unblocks 0.6 (SSE streams these rows), 0.8 (monitor page), 2.1 (cost from usage events) and 3.7 (audit log).

Principle **Small, verifiable steps**: we keep this to the table, the writer and one proof that a run lands ordered rows in Postgres.

## Scope
### In scope
- Alembic migration `0002` adding:
  - `runs`: `id` (UUID), `status`, `created_at`, `updated_at`.
  - `run_events`: `id`, `run_id` (FK → `runs`), `seq` (int, per run, starting at 1), `type`, `node_id` (nullable), `payload` (JSONB), `created_at`; unique `(run_id, seq)`.
- A `RunEvent` envelope model (Pydantic v2) and an `EventSink` protocol in the engine. The engine stays free of database code.
- Engine lifecycle events: `run_started`, `node_started`, `node_completed` / `node_failed` / `node_cancelled`, `run_completed` / `run_failed` / `run_cancelled`.
- Every `AgentEvent` from the runtime (including `text_delta`) written as a row, tagged with its `node_id`.
- `run_workflow` takes a sink and a run id, and assigns `seq` in emit order.
- An in-memory sink for engine tests.
- A new `packages/store` workspace package: SQLAlchemy 2.x async models for `runs` / `run_events` and a `PostgresEventSink`. The api package's Alembic env uses its metadata.

### Out of scope
- `POST /runs`, `GET /runs/{id}/events` and SSE (0.6).
- `LISTEN/NOTIFY` fan-out (0.6).
- Enforcing append-only in the database (trigger / revoked `UPDATE`/`DELETE`). Append-only is a convention of the store API for now; revisit with the audit log (3.7).
- Dropping or batching `text_delta` rows. Revisit if the log grows too large.
- Worker / queue wiring of runs (comes with 0.6 and later).
- Checkpointer and resume (1.3).
- Cost in USD (2.1). Usage events are stored as-is.
- Workspaces and tenancy columns (1.4).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where DB code lives | New `packages/store`, shared by api and (later) worker | Engine stays DB-free and testable with the fake runtime; worker does not have to depend on the api package. Matches the `uv` workspace layout in the tech stack. |
| Engine ↔ storage seam | `EventSink` protocol (`async emit(event)`) | Contract first: engine tests use an in-memory sink, Postgres is a plug-in. |
| Ordering | `seq` assigned by the engine per run, unique `(run_id, seq)` in Postgres | Order does not depend on clock or insert timing; a duplicate or gap is detectable. |
| Payload | JSONB holding the serialised `AgentEvent` or lifecycle details | One table for all event types; new `AgentEvent` members need no migration. |
| `text_delta` | Persisted like any other event | Keeps the log complete for the 0.6 live stream; no special case. |
| Write timing | One insert per event, committed as it is emitted | A live run is visible in Postgres while it runs, which 0.6 needs. |
| Run status | `runs.status` updated by the sink on run lifecycle events | `runs` is a mutable summary; `run_events` stays append-only. |

## Open questions
- None.
