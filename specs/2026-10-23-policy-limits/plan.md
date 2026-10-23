# Plan: Policy limits

The engine comes first, then the API and the UI, in slices that keep `main` working after each group.

## 1. Policy model
- [ ] `packages/engine/src/agentic_engine/policy.py`:
  - `Policy` (frozen Pydantic model: `agents_alive`, `agents_spawned`, `max_depth`, `loop_iterations`, `wall_time_s`);
  - `PLATFORM_POLICY` (8, 40, 2, 5, 7200);
  - `PolicyOverrides` (all fields optional);
  - `effective_policy(overrides) -> Policy`, which takes the lower of each pair;
  - `PolicyLimitExceeded(Exception)` carrying `limit`, `value`, `observed` and `node_id`.
- [ ] `spec/models.py`: keep `MAX_LOOP_ITERATIONS`, `MAX_AGENTS_ALIVE` and `MAX_AGENTS_SPAWNED` as aliases of `PLATFORM_POLICY` fields, so the schema caps stay the platform ceilings. Update their "Phase 3.2" docstrings.
- [ ] `events.py`: add `POLICY_LIMIT_EXCEEDED` with a payload docstring.
- [ ] Unit tests for `effective_policy` (null keeps the default, lower wins, higher is impossible).

## 2. Validation-time checks
- [ ] `spec/models.py` (or `policy.py`): `policy_problems(spec, policy) -> list[str]`, depth first, in the existing message style. It covers loop iterations, map concurrency and container depth (loop and map count as a level).
- [ ] Engine tests: one per check, plus a spec exactly at each limit that passes.

## 3. Runtime enforcement in the engine
- [ ] `graph/state.py`: add `spawned: Annotated[int, operator.add]` to `RunState`.
- [ ] `compile_workflow(..., policy: Policy = PLATFORM_POLICY)`:
  - pass the policy to each step;
  - before each agent start, raise `PolicyLimitExceeded("agents_spawned", …)` if the count would pass the limit;
  - `_map_items` checks `spawned + agents_per_item × len(items)` instead of the old per-map `ValueError`.
- [ ] A run-wide `asyncio.Semaphore(policy.agents_alive)` around `_run_step` agent calls, created per attempt (not checkpointed).
- [ ] `graph/run.py` `_finish`: on `PolicyLimitExceeded`, emit `policy_limit_exceeded`, then `run_failed` with the readable reason. Running nodes end `node_cancelled`.
- [ ] `run_workflow` / `resume_workflow` take `policy`.
- [ ] Check the docs template fits 40 spawned agents in its worst case (open question). Adjust its module cap if not.
- [ ] Engine tests on the fake runtime:
  - spawned is exceeded by a map;
  - spawned is exceeded by agents in sequence, including loop iterations;
  - the count survives a resume;
  - the alive semaphore never allows more than N concurrent calls (with a counting fake);
  - the event order and payload are correct, with no orphaned tasks.

## 4. Storage and run creation
- [ ] Alembic `0016_policy_limits`:
  - the `workspace_policies` table;
  - `runs.policy JSONB NOT NULL`, backfilled with `PLATFORM_POLICY`, then the default dropped.
- [ ] `store/models.py`: map the table and the column.
- [ ] `store`: `workspace_policy(sessions, workspace_id) -> Policy` and `replace_workspace_policy(...)`.
- [ ] `store/sink.py`: no new summary column. `run_failed.error` already sets `failure_reason`. Update the docstring table with `policy_limit_exceeded` (no summary change).
- [ ] `api/runs/routes.py`:
  - `POST /runs` and `POST /runs/{id}/rerun` load the effective policy, run `policy_problems` (422 with the list) and store `runs.policy`;
  - rerun uses the **current** workspace policy, not the original run's.
- [ ] API tests: 422 on each check, the policy is stored on the run, and rerun uses the current policy.

## 5. Wall time in the worker
- [ ] `store`: `active_seconds(sessions, run_id) -> float`, summed from `run_started`/`run_resumed` → `gate_waiting`/last event.
- [ ] `worker/main.py`:
  - load `run.policy`;
  - pass it to `run_workflow`/`resume_workflow`;
  - add `_watch_wall_time(worker, run, budget_left)` next to `_watch_cancel`;
  - when it fires, cancel the attempt, then write `policy_limit_exceeded` + `run_failed` (the same shape as `_end_cancelled`) and discard the sandbox.
- [ ] Worker integration tests (Testcontainers):
  - a run with `wall_time_s=2` on a slow fake stops with the reason;
  - a run that waited at a gate longer than its limit still resumes, so gate time is excluded;
  - after a worker restart mid-run, the earlier active time counts.

## 6. Workspace policy API
- [ ] `api/workspaces/models.py`: `WorkspacePolicy {defaults, overrides, effective}` and `PutPolicy`, with per-field `ge=1, le=ceiling` and the ceilings in the field descriptions.
- [ ] `api/workspaces/routes.py`: `GET` and `PUT /workspaces/{id}/policy`. `PUT` with all fields null resets.
- [ ] API tests: the round trip, 422 above a ceiling and on 0, and reset.
- [ ] Re-export OpenAPI (`scripts/export_openapi.py`) and regenerate the web client (`pnpm gen:api`).

## 7. UI
- [ ] `web/src/app/settings/page.tsx`: a "Run limits" card (shared Card and form components and tokens only):
  - one number field per limit with the platform default as placeholder and help text;
  - wall time entered as hours and minutes;
  - inline errors that mirror the ceilings;
  - Save and "Reset to defaults" (a confirmation dialog);
  - toasts on success and failure.
- [ ] Run console: a `policy_limit_exceeded` row in the Raw events tab gets a readable label. The header failure reason needs no change. Confirm it shows the full reason without truncation at 375 px.
- [ ] Vitest component tests for the card: validation, minutes ↔ seconds, reset.

## 8. Docs
- [ ] `specs/tech-stack.md`, security section: limits are workspace-configurable down from the platform ceilings and frozen per run, and wall time excludes gate waits.
- [ ] `CHANGELOG.md` entry (done by `open-pr`).
