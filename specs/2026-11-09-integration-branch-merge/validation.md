# Validation: Integration branch: merge worker branches before the final PR

## Done when (from roadmap)
> Parallel writers produce one PR

For 6.3 this means: an orchestrator whose tasks write on separate branches ends with one integration branch holding every completed task, and `openPR` from the orchestrator publishes that branch as one PR after a gate.

## Automated checks
- [ ] Engine unit tests (`packages/engine/tests/test_orchestrator_integrate.py`, fake sandbox):
  - 3 writer tasks merge into `agent/<run>/<orch>` in plan order; `branch_integrated` lists all 3; `data.writers == [<orch>]`.
  - A body with no writer has no integrate step and no `branch_integrated`.
  - A task with no commits is `empty`, not merged and not failed.
  - A conflict with `replan` left: `branch_integrated` lists the task with its conflict paths, the task is `failed` in the plan and the replan input with ``conflicts with earlier tasks on …``, the other tasks are still merged, and round 2's task merges on top.
  - A conflict in the last round: the orchestrator fails with ``task '<id>' conflicts with earlier tasks on …``.
  - A resumed run asks for every completed task and merges none twice; a run continued after a gate does not merge again.
- [ ] Validation tests (`test_orchestrator_spec.py`): `openPR` from the orchestrator behind a gate is valid; from the orchestrator with no gate it is `publish_without_gate`; from a node in its body it is a `reference` issue that names the orchestrator; from an orchestrator whose body does not write it is "not a writer".
- [ ] Gate tests (`test_orchestrator_integrate.py`, `packages/worker/tests/test_review.py`): a gate after the orchestrator shows the integration branch's files under the orchestrator's id and edits commit to it; the worker gives the `github` server the orchestrator as a writer, so `openPR` pushes `agent/<run>/<orch>`.
- [ ] Docker sandbox test (`packages/sandbox/tests/test_integrate.py`): two branches merge cleanly with two `--no-ff` merge commits; a conflicting branch is reported with its path, and afterwards `git status` shows no merge in progress; a repeated call is a no-op.
- [ ] Existing suites stay green: `test_orchestrator.py`, `test_orchestrator_replan.py`, `test_resume.py`, `test_gate*.py`.
- [ ] `uv run ruff check`, `uv run pyright` (strict), and the backend test suite run locally. The schema export and fixtures are regenerated, with no diff left over.
- [ ] No generated schema or API type changes (`scripts/export_workflow_schema.py` and `export_openapi.py` leave no diff).

## Manual / demo checks
- [ ] None required by the chosen validation. Optionally, with the local stack: an orchestrator workflow whose hub plans 3 tasks that each write one file, then a gate, then `openPR` from the orchestrator. Expected: one PR from `agent/<run>/<orch>` with 3 merge commits.

## Merge criteria
- [ ] All the automated checks above pass locally (CI minutes are limited: run them locally and do not wait on CI).
- [ ] `tech-stack.md` (Orchestrator and Gate review contracts, decision-log rows) and the roadmap's 6.3 row (plan link) are updated in the same PR.
- [ ] `CHANGELOG.md` has an `## [Unreleased]` entry.
- [ ] No token or remote URL with credentials appears in an event, a log line or an error (merges run in the sandbox and never touch the remote).
