# Validation: Run summaries API

## Done when (from roadmap)
> The API lists past runs with status taken from the event log

## Automated checks

### Projection (Testcontainers Postgres, fake runtime, `packages/store/tests/`)
- [ ] Completed run: `status=completed`, `started_at` = `run_started.created_at`, `finished_at` = `run_completed.created_at`, `failure_reason`, `pr_url`, `waiting_gate` null.
- [ ] Failed run: `status=failed`, `failure_reason` equals `run_failed.payload.error`, `finished_at` set.
- [ ] Run paused at a gate: `status=waiting`, `waiting_gate = {node_id, title}` of the gate, `finished_at` null; after approval and `run_resumed`, `waiting_gate` is null and `status=running` then `completed`.
- [ ] Rejected gate: `status=cancelled`, `waiting_gate` null, `finished_at` set.
- [ ] Run with a `pr_opened` event: `pr_url` equals its `payload.url`.
- [ ] Resumed run (second attempt emits `run_resumed`): `started_at` keeps the first start.
- [ ] For each case above, the summary row agrees with a fold over `list_run_events` (status taken from the event log).

### API and pagination (`packages/api/tests/test_runs.py`)
- [ ] `GET /runs` returns runs newest first (`created_at`, then `id`).
- [ ] With 7 runs and `limit=3`: following `next_cursor` gives 3 + 3 + 1 items, no duplicates, no gaps, last page `next_cursor = null`.
- [ ] A run created between page requests does not shift or duplicate later pages.
- [ ] `status=waiting` returns only waiting runs; `status=failed&status=cancelled` returns both.
- [ ] `template=generate-docs` returns only runs started from that template.
- [ ] `repo=<url>` returns only runs on that repo.
- [ ] Runs of another workspace are not listed; unknown `workspace_id` → `404`.
- [ ] Malformed `cursor` → `422`; `limit=0` or `limit=101` → `422`.
- [ ] `GET /runs/{id}` returns `RunDetail` with `input`, `failure_reason`, `workflow {id, name}`, `template_id`, `repo`, `duration_ms`; unknown id → `404`.
- [ ] `GET /runs/{id}/events` still streams (route not shadowed).

### CI
- [ ] `ruff`, `mypy --strict`, `pytest` (all packages) green.
- [ ] Existing `test_migrations.py` upgrade/downgrade round trip passes with `0010_run_summary`.
- [ ] OpenAPI check: `web/openapi.json` and `web/src/api/` have no diff after regeneration.
- [ ] Web `typecheck`, lint and tests still green (generated types only).

## Manual / demo checks
- [ ] `docker compose up`, start one docs run that completes and one with an invalid repo that fails, then:
  - `curl localhost:8000/runs` → both, newest first, statuses `completed` and `failed`.
  - `curl localhost:8000/runs/<failed-id>` → `failure_reason` set, `duration_ms` set.
  - Start a run that pauses at a gate → `curl 'localhost:8000/runs?status=waiting'` lists it with `waiting_gate.title`.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] `PostgresEventSink` and `Run` docstrings describe the full projection.
- [ ] No full `spec` or event payloads in list responses (only `workflow {id, name}` and `waiting_gate {node_id, title}`).
- [ ] Roadmap row 2.3 marked done by the implementing PR.
