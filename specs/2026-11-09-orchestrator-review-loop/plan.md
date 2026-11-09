# Plan: Orchestrator in a loop

Contract, then engine, then console (interview choice). The repo stays green after each group.

## 1. Contract
- [ ] `specs/tech-stack.md`: "Orchestrator (API contract)" → Where (in a loop's body), Plans per iteration, the hub's input in a later iteration, the integration branch kept across iterations, events with `iteration`, limits and resume; loop rules (an orchestrator's writers allowed, plain writers not); decisions-log rows.
- [ ] `agentic_engine/spec/models.py`: `_not_in_loop` lets an orchestrator through (its body is still checked by `orchestrator_issues`, and its writers do not count as a loop's writers); `artifact` and publish checks unchanged. Tests in `test_orchestrator_spec.py` and `test_validate.py`: allowed in a loop; still refused in a map, a branch, another orchestrator; a plain writer in the same loop still refused.

## 2. Engine
- [ ] `graph/state.py`: `plans` and `rounds` keyed by `<orchestrator>#<iteration>` inside a loop (checkpoints from before stay keyed by id); `map_results` likewise.
- [ ] `graph/compile.py`: the orchestrator's entry reads the enclosing loop's iteration; iteration ≥ 2 asks the hub with `{input, iteration, previous}` and `hub_iteration_instructions`; a task id used before is refused (``the hub of 'implement' planned task 'b' again``).
- [ ] Integration (`agentic_sandbox.integrate`, `SandboxIntegrator`): keep `agent/<run>/<orchestrator>` across iterations; later task worktrees are made from its head (the `BranchIntegrator` says where tasks start).
- [ ] `recursion_limit`: a loop's orchestrator counts per iteration.
- [ ] Events: `iteration` on `plan_made`, `task_*`, `replan_started`, `branch_integrated` inside a loop.
- [ ] Tests (fake runtime, `test_orchestrator_loop.py`): a review rejects once then approves: iteration 2 plans with the review as data, its tasks start from the integration branch, one branch holds both iterations' merges, the publish after the loop sees one writer; `max_iterations` stops it; a resume mid-iteration-2 does not ask the hub again for iteration 1 or 2; agents of every iteration count on `agents_spawned`.
- [ ] `test_orchestrator_loop_fixture.py` records `schemas/fixtures/orchestrator-loop-run.json` for the console.

## 3. Console
- [ ] `@/runs/timeline`: an orchestrator inside a loop iteration keeps its own tasks and rounds per iteration (events tagged `iteration`).
- [ ] Step list and Output: each iteration's orchestrator shows its plan, what the previous iteration's review said (as text) and its integration; the iteration headings already exist.
- [ ] Vitest from the fixture.

## 4. Workflow, specs, changelog
- [ ] `team-review-pr` v2 (loop around `implement`, `synthesizer`, `reviewer`; gate and `open_pr` after it; per-task verdict trick removed), validated, stored in the dev stack as version 2, and its spec kept as an engine test fixture that must validate.
- [ ] `specs/roadmap.md` `[Plan]` link; `CHANGELOG.md` entry.
