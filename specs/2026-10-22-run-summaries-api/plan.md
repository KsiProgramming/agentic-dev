# Plan: Run summaries API

Order: store first, then API. Each group leaves the project working and CI green.

## 1. Schema and backfill
- [x] `packages/store/src/agentic_store/models.py`: add `template_id`, `repo_url`, `started_at`, `finished_at`, `pr_url`, `failure_reason`, `waiting_gate` (JSONB), `rerun_of` (FK `runs.id`) to `Run`; index `ix_runs_workspace_created` on `(workspace_id, created_at DESC, id DESC)`. Update the `Run` docstring.
- [x] `packages/api/alembic/versions/0010_run_summary.py`: add the columns and index; backfill from `run_events` with `UPDATE … FROM (SELECT …)`:
  - `repo_url = repo->>'url'`
  - `started_at = min(created_at) where type = 'run_started'`
  - `finished_at`, `failure_reason` from the final run event (`payload->>'error'` for `run_failed`)
  - `pr_url` from the last `pr_opened`
  - `waiting_gate` for runs with `status = 'waiting'` from their last `gate_waiting` (`node_id`, `payload->>'title'`)
  - Downgrade drops the index and columns.
- [x] `packages/store/src/agentic_store/runs.py`: `create_run` takes `template_id` and writes `repo_url`.
- [x] `packages/api/src/agentic_api/runs/routes.py`: `POST /runs` passes `body.template.id` when given.

## 2. Projection in the event sink
- [x] `packages/store/src/agentic_store/sink.py`: replace the status-only update with a `summary_values(event) -> dict` that returns the columns each event type sets (see requirements → Projection), merged into the one `UPDATE runs` already issued in `emit`.
- [x] `started_at` uses `coalesce(started_at, :ts)` so a resumed attempt keeps the first start.
- [x] Clear `waiting_gate` on `gate_decided`, `run_resumed` and final events.
- [x] Update the `PostgresEventSink` docstring with the full projection table.
- [x] Tests in `packages/store/tests/` (Testcontainers Postgres, fake runtime): see validation → Projection.

## 3. Store queries
- [x] `packages/store/src/agentic_store/summaries.py`:
  - `RunSummaryRow` dataclass (all summary fields + `input`, `spec` name/id).
  - `encode_cursor` / `decode_cursor` (`InvalidCursorError` on bad input).
  - `list_run_summaries(sessions, workspace_id, *, statuses, template_id, repo_url, cursor, limit) -> tuple[list[RunSummaryRow], str | None]`: keyset on `(created_at, id)`, fetch `limit + 1` to know if there is a next page; selects only needed columns (`spec->'id'`, `spec->'name'`, not the full spec).
  - `get_run_summary(sessions, run_id) -> RunSummaryRow | None`.
- [x] Export from `agentic_store/__init__.py`.

## 4. API routes and models
- [x] `packages/api/src/agentic_api/runs/models.py`: `WorkflowRef`, `WaitingGate`, `RunSummary`, `RunDetail`, `RunSummaryPage`; `duration_ms` as a computed field.
- [x] `packages/api/src/agentic_api/runs/routes.py`:
  - `GET /runs` (`operation_id="listRuns"`): query params `workspace_id`, `status: list[RunStatusFilter]`, `template`, `repo`, `cursor`, `limit` (1–100, default 25); `422` on bad cursor; `404` on unknown workspace.
  - `GET /runs/{run_id}` (`operation_id="getRun"`): `404` if unknown.
  - Route order: `/{run_id}` must not shadow `/{run_id}/events` (it doesn't, but test both).
- [x] Tests in `packages/api/tests/test_run_summaries.py`: see validation → API and pagination.

## 5. Contract export
- [x] `uv run python scripts/export_openapi.py && (cd web && pnpm gen:api)`; commit `web/openapi.json` and `web/src/api/schema.d.ts`.
- [x] No web code changes beyond the generated files (2.4 consumes them).
