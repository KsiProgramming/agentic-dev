# Validation: Replan policy (on-failure)

## Done when (from roadmap)
> A failed worker triggers a replan within limits

Made checkable: on the fake runtime, an orchestrator with `replan: {on: "failure", max_rounds: 1}` whose plan has 3 tasks, one of which fails, emits `replan_started`, asks the hub once more with the failure as data, runs the new tasks, and completes with the completed outputs of both rounds; with `max_rounds` used up, or a replan over `agents_spawned`, it stops cleanly.

## Automated checks
Engine tests on the fake runtime (`packages/engine/tests/test_orchestrator_replan.py`), no network:
- [x] **Replan then complete**: plan `[a, b, c]`, `b` fails → `a` and `c` finish (not cancelled), `replan_started {round: 2, failed: [b]}`, `plan_made {round: 2, tasks: [b2]}`, `b2` runs with index 3 → `node_completed {tasks: 4, completed: 3, rounds: 2}`, output `a, c, b2` in plan order.
- [x] **Settle**: with `max_concurrency: 1` and plan `[a, b, c]`, `a` fails → `b` and `c` end `dropped` without running; the replan input lists them as dropped.
- [x] **Rounds exhausted**: `max_rounds: 1`, the replanned task fails too → orchestrator `node_failed` naming the task and the rounds used; no third hub turn.
- [x] **Within limits**: a replan whose new tasks would exceed `agents_spawned` → `policy_limit_exceeded {limit: "agents_spawned"}` and a failed run, no new worker; a replan planning more than `max_workers − completed` tasks fails as a typed port (`node_failed` with `port`).
- [x] **Unique ids**: a replan reusing an earlier task id (failed or completed) fails the orchestrator.
- [x] **Empty replan**: completes when some task completed; fails with the last error when none did.
- [x] **Failure is data**: the replan turn's request has the hub's instructions plus the fixed replan paragraph, and the failed task's error only in its input.
- [x] **Off by default**: with `replan` unset every 6.1 orchestrator test passes unchanged (one failure cancels the others).
- [x] **Reduce**: a `concat` reduce after a replanned orchestrator sees only completed tasks, by task id.
- [x] **Resume mid-replan**: a worker restart after round 2 was planned and one of its tasks completed resumes without any hub turn and runs only the unfinished task (LangGraph in-memory checkpointer, as 6.1's resume test); a checkpoint from 6.1 (tasks without `round`) resumes as round 1.
- [x] **Spec and manifest**: `test_orchestrator_spec.py` cases for `replan` (valid, `max_rounds` 0/4 and bad triggers refused, the replan plan schema's cap); the manifest test passes; `schemas/fixtures/node-types.json` and `schemas/workflow-spec.v0.json` are not stale.
- [x] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict) and `uv run pytest` pass locally.
- [x] `cd web && pnpm lint && pnpm typecheck && pnpm test` pass with the regenerated fixtures and API types.

## Manual / demo checks
- [x] `uv run pytest packages/engine -k replan -v` shows the replan-then-complete test and its event sequence.

## Merge criteria
- [ ] All checks above pass locally (CI minutes are limited; CI is not watched run by run).
- [x] `specs/tech-stack.md` "Orchestrator (API contract)" and the decisions log describe replan; `roadmap.md` 6.2 links this plan.
- [x] `CHANGELOG.md` has an entry under `## [Unreleased]`.
- [x] No task output or error text appears in a hub's instructions, only in its input.
