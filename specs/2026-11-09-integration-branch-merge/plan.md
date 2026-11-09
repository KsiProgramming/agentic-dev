# Plan: Integration branch: merge worker branches before the final PR

Engine first (the user's choice). Every group leaves `main` working: until group 3 lifts the `openPR` refusal, the integration branch exists, but nothing publishes it.

## 1. Sandbox merge and the `Integrator` protocol
- [ ] `agentic_sandbox/integrate.py`: `integrate_branches(sandbox, run_id, target, sources)`. It creates or reuses the worktree and branch `agent/<run>/<target>` from the clone's `HEAD`. For each source branch in order, it skips the branch if it is missing, has no commits past the base, or is already an ancestor of the target. Otherwise it runs `git merge --no-ff -m "Merge task '<id>': <title>"` with the agent identity. On a conflict it collects the paths (`git diff --name-only --diff-filter=U`) and runs `git merge --abort`. It returns `{merged, skipped, conflicts: [{id, paths}], head}`. Like `review.py`, it runs as one shell script per call.
- [ ] Add the same behaviour to `agentic_sandbox/fake.py`, so engine tests can model clean merges, conflicts and empty branches.
- [ ] `agentic_engine/integrate.py`: the `Integrator` protocol (`integrate(orchestrator_id, tasks) -> IntegrationResult`), `IntegrationResult`, and `IntegrationError` for a sandbox failure, which is not a conflict.
- [ ] `agentic_worker/integrate.py`: `SandboxIntegrator` over the run's sandbox. Wire it in `main.py` next to `SandboxGateReview`.

## 2. The `<id>.integrate` step in the orchestrator
- [ ] `graph/compile.py`: for an orchestrator whose body has a writer, `<id>.join` goes to `<id>.integrate`, which then goes to `<id>.replan` or the orchestrator's end, as the join did before. Add one more step per round to the step limit.
- [ ] Merge the round's completed tasks that are not yet in `RunState.integrated[<id>]`, in plan order, and record the merged and skipped ids. A conflicting task's result becomes `failed` with the conflict error (at most 10 paths), so 6.2's settle-and-replan logic sees it unchanged. In the last round, the orchestrator fails like the round's first failed task.
- [ ] `IntegrationError` fails the orchestrator with ``cannot build the integration branch: …``.
- [ ] Events: `branch_integrated` (`round`, `branch`, `merged`, `skipped`, `conflicts`, `head`) in `events.py`. `task_completed` with `status: "failed"` for a task that conflicts. `node_completed` gains `branch` and `merged`.
- [ ] Output `data`: `writers` is `[<id>]` when anything was merged, otherwise `[]`. Add `branch` and `merged`. `plan` keeps each task's own key.
- [ ] Tests in `packages/engine/tests/test_orchestrator_integrate.py`: clean merge of 3 tasks in plan order; a non-writer body has no integrate step; tasks with no commits are skipped; a conflict with replan (the hub sees the error and round 2 merges on top); a conflict in the last round fails the orchestrator; resume after a crash merges nothing twice; an empty plan.

## 3. Gate review, validation and `openPR`
- [ ] `graph/run.py` `_task_writers` and `agentic_worker/review.py`: a gate after the orchestrator shows the integration branch as writer `<orchestrator id>`. Edits commit there (`FileEdit.node_id` is the orchestrator id).
- [ ] `spec/models.py` `_publish_issue`: `from_node` naming an orchestrator whose body writes passes the writer check and still needs a gate between them. A node inside the body is still a `reference` issue: ``… is a worker of 'fix'; publish 'fix' instead``. `node_tools` or the writer check counts an orchestrator's body.
- [ ] `agentic_tools/github/server.py` and the worker's writer list: include orchestrator ids, so `openPR` pushes `branch_name(run, <orch>)`.
- [ ] Tests: `test_validate.py` and `test_orchestrator_spec.py` (publish from the orchestrator is allowed, from its worker is refused, a publish with no gate is refused); `test_gate_review.py` and `test_open_pr.py` (the integration branch is shown, edited and published).

## 4. Contract, schemas and docs
- [ ] `specs/tech-stack.md`: update "Orchestrator (API contract)" (the Integration subsection, Output, Events, Writers, Compile and resume) and "Gate review" (an orchestrator's writer). Add decision-log rows: "Integration branch (6.3)", "Merge conflict (6.3)", and replace "Task writers (6.1)"'s "publishing waits for 6.3".
- [ ] `specs/roadmap.md`: add a `[Plan](2026-11-09-integration-branch-merge/requirements.md)` link to row 6.3.
- [ ] Regenerate the `schemas/` export, the engine fixtures and the web API types. Web changes are expected only in the generated types.
- [ ] `docs/` architecture or flow page for orchestrator writers, if one covers them.
- [ ] `CHANGELOG.md` `## [Unreleased]` entry.

## 5. Docker sandbox test
- [ ] `packages/sandbox/tests/test_integrate.py` (docker-marked, as `test_docker_sandbox.py`): in a real clone, two task worktrees edit different files and merge cleanly into `agent/<run>/<orch>` with two merge commits; a third that edits the same lines conflicts and is reported with its path; the integration branch is left clean with no merge in progress; a second call merges nothing.
