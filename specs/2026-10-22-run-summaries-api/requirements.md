# Run summaries API

Roadmap phase: 2.3
Branch: plan/2.3-run-summaries-api

## Context
Today a run can only be read as a raw event stream (`GET /runs/{id}/events`), and nothing lists past runs. The Runs page (2.4), run console header (2.5), approval dock badge (2.6) and rerun (2.7) all need a run *summary*: status, what ran, on which repo, how long it took, its PR or why it failed, and the gate it waits at. This phase adds that read API. It is backend only; 2.4 is the first UI to use it.

What exists: the `runs` row already keeps `status`, projected by `PostgresEventSink` in the same transaction as each event insert (`run_started`/`run_resumed` → `running`, `gate_waiting` → `waiting`, final events → end status). The other summary fields are only in `run_events` today, and the template id is not stored at all (it is turned into a spec at `POST /runs`).

This phase does not depend on 1.12, which is still unplanned.

Principles and choices that apply:
- **Mission 9, Nothing is lost:** every run is listed with its outcome and can be opened later.
- **Mission 6, Transparency:** the summary is a projection of the append-only event log, never a second source of truth.
- **Tech stack → Run history and rerun (API contract):** `GET /runs` newest first, cursor pagination, filters `status`, `template`, `repo`. Status, timings, PR URL and waiting gate come from events and are *kept in the `runs` row when events are written, so listing does not scan the log*. `GET /runs/{id}` has the same shape plus `input` and `failure_reason`.
- **Tech stack → Backend:** FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic; OpenAPI feeds the generated TS client.

## Scope
### In scope
- **New `runs` columns** (Alembic migration `0010_run_summary`):
  - `template_id` (text, null): set at `POST /runs` from `template.id`; null for a raw workflow.
  - `repo_url` (text, null): copied from `repo.url` at create, for filtering and indexing.
  - `started_at`, `finished_at` (timestamptz, null).
  - `pr_url` (text, null).
  - `failure_reason` (text, null).
  - `waiting_gate` (JSONB, null): `{node_id, title}` of the gate the run waits at.
  - `rerun_of` (UUID, null, FK → `runs.id`): the column only; 2.7 sets it.
  - Index `(workspace_id, created_at DESC, id DESC)` for listing.
- **Backfill** in the same migration: fill the new columns of existing runs from their `run_events` (and `template_id` stays null for them, since it was never recorded).
- **Projection in `PostgresEventSink`**, same transaction as the event insert:
  - first `run_started` → `started_at` (kept on later attempts).
  - `run_completed` / `run_failed` / `run_cancelled` → `finished_at`.
  - `node_failed` with an `error` → `failure_reason = "node <id>: <error>"`; `run_failed` with an `error` (the engine or worker itself failed) → that error. A node failure's `run_failed` carries only `stopped_at`, so the node's error is the reason. `run_completed` / `run_cancelled` clear it.
  - `pr_opened` → `pr_url` from `payload.url` (last one wins).
  - `gate_waiting` → `waiting_gate`; `gate_decided`, `run_resumed` and final events → `waiting_gate = null`.
- **Store queries** in `agentic_store`: `list_run_summaries(workspace_id, status?, template?, repo?, cursor?, limit)` and `get_run_summary(run_id)`.
- **API** in `agentic_api.runs`:
  - `GET /runs?workspace_id&status&template&repo&cursor&limit` → `RunSummaryPage {items: RunSummary[], next_cursor: str | null}`.
  - `GET /runs/{id}` → `RunDetail` (= `RunSummary` + `input` + `failure_reason`); `404` if unknown.
- **`RunSummary` shape:** `id`, `workspace_id`, `status`, `workflow {id, name}` (from the spec), `template_id`, `repo` (`RepoSource` or null), `created_at`, `started_at`, `finished_at`, `duration_ms` (finished − started, null while live; the client ticks a live one), `pr_url`, `waiting_gate`, `rerun_of`.
- Regenerated `web/openapi.json` and `web/src/api/schema.d.ts` (CI already checks they are current).

### Out of scope
- Any UI: the Runs page is 2.4, the console header 2.5.
- Setting `rerun_of` and `POST /runs/{id}/rerun`: 2.7.
- Live updates of the list (SSE on `/runs`): 2.4 decides between polling and a stream.
- Cost per run in the summary: 3.1.
- Auth / per-user visibility: runs are scoped by workspace only, as today.
- Free-text search, sort options other than newest first, and a total count.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where summaries live | Extra columns on `runs`, written by `PostgresEventSink` in the event's transaction | Tech-stack contract: listing never scans the log; same-transaction write means the row can never be ahead of or behind the log. |
| Old runs | One-off SQL backfill in the migration | 2.4 shows the full history, not only runs made after 2.3 (mission 9). |
| Cursor | Opaque base64url of `(created_at, id)`; keyset query `(created_at, id) < cursor` | Stable under inserts, no offset scans; `id` breaks ties. Invalid cursor → `422`. |
| Page size | `limit` default 25, max 100 | Enough for a screen, bounded for the DB. |
| Workspace | `workspace_id` query param, default workspace, like `POST /runs` | No auth yet; matches existing routes. |
| `repo` filter | Exact match on `repo_url` | `RepoSource.url` is already normalised at create; a dedicated column can be indexed later. |
| `template` filter | Exact match on `template_id` | Template ids are stable (`generate-docs`). |
| `status` filter | Repeatable (`?status=failed&status=cancelled`) | 2.4 needs "Needs approval" (`waiting`) and "finished" groups. |
| Waiting gate | `{node_id, title}` only; full prompt/artifact stay in the event | Keeps the row small; the dock (2.6) reads details from the events. |
| Duration | Computed in the response, not stored | Derived data; avoids a second write. |

## Open questions
- None. (Ordering "Needs approval first" is a 2.4 UI concern: it can call `?status=waiting` then the rest.)
