# Validation: `orchestrator` primitive

## Done when (from roadmap)
> A hub plans N subtasks and the engine spawns N workers

Made checkable: on the fake runtime, a hub whose plan has 3 tasks produces exactly 3 worker runs (3 sets of events tagged `task`), never more than `max_concurrency` at once, and the orchestrator completes with the 3 outputs in task order.

## Automated checks
Engine tests on the fake runtime (`packages/engine/tests/`, plus the sandbox and tools packages for writers), no network:
- [ ] **N plans → N workers**: plan of 3 → 3 workers, `plan_made` lists them, output in task order, `node_completed {tasks: 3, completed: 3}`.
- [ ] **Concurrency**: `max_concurrency: 2` with 4 tasks never runs more than 2 workers at once; workers wait for `agents_alive` slots.
- [ ] **Plan bounds**: a plan with more than `max_workers` tasks, a duplicate task id or a missing field fails the orchestrator as a typed port (`node_failed` with `port`); an empty plan completes with `[]` and no worker events.
- [ ] **Agents spawned**: a plan whose workers would exceed `agents_spawned` ends the run `failed` with `policy_limit_exceeded` (`limit: "agents_spawned"`).
- [ ] **Failed worker**: one failing worker cancels the running ones and fails the orchestrator, naming the task.
- [ ] **Resume**: a worker restart after the plan and one completed task resumes without asking the hub again and runs only the remaining tasks (checkpointer test, Testcontainers Postgres).
- [ ] **Task is data**: the worker agent's request has the spec's instructions unchanged and the task in its input.
- [ ] **Reduce**: `concat` and `dedupe` reduces with `from: <orchestrator>` see sources keyed by task id.
- [ ] **Writers**: a writer worker commits on `agent/<run>/<orch>--<task>`; a gate after the orchestrator shows each task's changes and commits edits to the right branch; `github.openPR` with `from_node` the orchestrator or a node in its body is a `reference` issue.
- [ ] **Validation**: each forbidden body node and each forbidden placement gives `not_allowed_in_orchestrator` at the right path; `max_concurrency` over `agents_alive` and depth over `max_depth` give policy issues.
- [ ] **Manifest**: the manifest test (every `Node` member has one, its `default` is a valid step) passes; `schemas/fixtures/node-types.json` is not stale.
- [ ] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict) and `uv run pytest` pass locally.
- [ ] `cd web && pnpm test` passes with the regenerated fixtures (no web code changed).

## Manual / demo checks
- [ ] `uv run pytest packages/engine -k orchestrator -v` shows the N-tasks → N-workers test and its event sequence.
- [ ] Optional, not required to merge: the sample spec run locally on Claude (`docker compose up`, `POST /runs` with the sample) shows the hub's plan and one step per task in the run console.

## Merge criteria
- [ ] All checks above pass locally (CI minutes are limited; CI is not watched run by run).
- [ ] `specs/tech-stack.md` has the "Orchestrator (API contract)" section and decisions-log rows; `roadmap.md` 6.1 links this plan.
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]`.
- [ ] No secret, token or task text from repo content appears in instructions or logs; worker branches are never pushed in this phase.
