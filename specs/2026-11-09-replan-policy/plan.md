# Plan: Replan policy (on-failure)

Contract first: the spec field, validation and the written contract land before runtime code, and the engine suite stays green after each group. With `replan` unset every 6.1 test passes unchanged.

## 1. Contract: spec field, validation, docs
- [ ] `agentic_engine/spec/models.py`: `OrchestratorReplan` (`on: Literal["failure"]`, `max_rounds` 1..3) and `OrchestratorNode.replan: OrchestratorReplan | None = None`; `agents_spawned` worst case `(1 + max_rounds) × (1 + max_workers × body)`.
- [ ] `orchestrator_plan_schema(node, max_tasks=…)` takes the cap so a replan's schema allows `max_workers − completed` tasks; `TASK_ID_PATTERN` unchanged.
- [ ] `scripts/export_workflow_schema.py` → `schemas/workflow-spec.v0.json`; graph ops' `setParam` accepts `replan` (ops tests).
- [ ] `specs/tech-stack.md`: update "Orchestrator (API contract)" (spec, replan turn, task ids, output, limits, events, resume) and replace the "Replanning is 6.2" notes; decisions-log rows from requirements. `CHANGELOG.md` entry under `[Unreleased]`; roadmap 6.2 links this plan.
- [ ] Tests (`test_orchestrator_spec.py`): a spec with `replan` validates; `max_rounds` 0 and 4 are refused; `agents_spawned` worst case with replan; a spec over the limit gives a `policy_limit` issue.

## 2. Runtime: settle, replan, end
- [ ] `graph/compile.py` `_Workers`: with `replan` set, a failed task stops new starts but does not cancel the running ones; unstarted tasks end `dropped` (`task_completed {status: "dropped"}`); without `replan`, 6.1's cancel path unchanged.
- [ ] Graph shape: `<id>.join` routes to a new `<id>.replan` node when a task of the latest round failed and rounds remain; `<id>.replan` runs the hub's replan turn (`hub_replan_instructions`, input `{input, round, tasks}`), checks ids against all earlier rounds, counts the turn and new tasks on `agents_spawned`, appends the round to `plans` (each task with `round`), and fans out the new tasks with indices continuing after the last; then `<id>.join` again.
- [ ] `graph/state.py`: `merge_plans` appends a round rather than replacing (or the node writes the full list); checkpoints from 6.1 (tasks without `round`) read as round 1.
- [ ] Join: completes when every task of the latest round completed; fails naming the failed task and rounds used when none are left; an empty replan completes if any task completed. Output and `data` (`tasks` with `round` and status, `outputs`, `writers` of completed tasks, `rounds`).
- [ ] Events (`events.py`): `REPLAN_STARTED` (`round`, `failed`, `dropped`); `plan_made.round`; `node_completed.rounds`. Hub usage per round goes to the orchestrator (budget metering unchanged).
- [ ] Reduce sources (`from: <orchestrator>`) list only completed tasks, by task id.

## 3. Manifest, fixtures, web types
- [ ] `agentic_engine/nodes.py`: the orchestrator manifest's `parameters` include `replan` (advanced group); `default` unchanged.
- [ ] Regenerate `schemas/fixtures/node-types.json`, the OpenAPI export and `web/src/api/schema.d.ts`; `cd web && pnpm lint && pnpm typecheck && pnpm test` pass with no hand-written web change.
- [ ] A sample spec `orchestrator-replan.json` in the engine test fixtures (the docs sample with `replan: {on: "failure", max_rounds: 2}`).

## 4. Tests on the fake runtime
- [ ] `packages/engine/tests/test_orchestrator_replan.py` with the cases in validation.md (scripts keyed by node id, task and round).
