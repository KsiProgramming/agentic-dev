# Plan: Integration branch: merge worker branches before the final PR

Engine first (the user's choice). Every group leaves `main` working: until group 3 lifts the `openPR` refusal, the integration branch exists, but nothing publishes it.

## 1. Sandbox merge and the `Integrator` protocol
- [x] `agentic_sandbox/integrate.py`: `integrate_branches(sandbox, run_id, target, sources)`. It creates or reuses the worktree and branch `agent/<run>/<target>` from the clone's `HEAD`. For each source branch in order: `empty` if it is missing or has no commits past the base; `merged` if it is already in the target; otherwise `git merge --no-ff -m "Merge task '<id>': <title>"` with the agent identity. On a conflict it lists the paths (`git diff --name-only --diff-filter=U -z`) and runs `git merge --abort`. It returns `IntegrationOutcome(branch, head, merged, empty, conflicts)`. Like `review.py`, it runs as one shell script per call.
- [x] No change to `fake.py`: the fake sandbox runs real git, so the sandbox tests cover both backends. Engine tests use a fake `BranchIntegrator`.
- [x] `agentic_engine/integrate.py`: the `BranchIntegrator` protocol (`integrate(orchestrator_id, sources) -> Integration`), `MergeRequest`, `Integration`, `IntegrationError` for a sandbox failure (not a conflict), and `conflict_error`.
- [x] `agentic_worker/integrate.py`: `SandboxIntegrator` over the run's sandbox, wired in `main.py` next to `SandboxGateReview` and passed through `run_workflow`/`resume_workflow` (`integrator=`).

## 2. The `<id>.integrate` step in the orchestrator
- [x] `graph/compile.py`: for an orchestrator whose body has a writer, the tasks go to `<id>.integrate`, then to `<id>.join`, which goes on to `<id>.replan` or the orchestrator's end as before. One more step per round in the step limit.
- [x] Merge every completed task, in plan order, and record the latest outcome in `RunState.integrated`. A conflicting task's result becomes `failed` with the conflict error (at most 10 paths), so 6.2's settle-and-replan logic sees it unchanged. In the last round, the orchestrator fails like the round's first failed task.
- [x] `IntegrationError` fails the orchestrator with ``cannot build the integration branch: …``.
- [x] Events: `branch_integrated` (`round`, `branch`, `head`, `merged`, `empty`, `conflicts`) in `events.py`. `node_completed` gains `branch` and `merged`.
- [x] Output `data`: `writers` is `[<id>]` when anything was merged, otherwise `[]` (each task's key without an integrator). Add `branch` and `merged`.
- [x] Tests in `packages/engine/tests/test_orchestrator_integrate.py`: clean merge of 3 tasks in plan order; a non-writer body has no integrate step; tasks with no commits are skipped; a conflict with replan (the hub sees the error and round 2 merges on top); a conflict in the last round fails the orchestrator; resume after a crash merges nothing twice; an empty plan.

## 3. Gate review, validation and `openPR`
- [x] `graph/run.py` `_task_writers` and `agentic_worker/review.py`: a gate after the orchestrator shows the integration branch as writer `<orchestrator id>`. Edits commit there (`FileEdit.node_id` is the orchestrator id).
- [x] `spec/models.py` `_publish_issue`: `from_node` naming an orchestrator whose body writes passes the writer check and still needs a gate between them. A node inside the body is still a `reference` issue: ``… is a worker of 'fix'; publish 'fix' instead``. `node_tools` or the writer check counts an orchestrator's body.
- [x] The worker's writer list for the `github` server includes the orchestrators whose tasks write, so `openPR` pushes `branch_name(run, <orch>)` (no change in the server itself).
- [x] Tests: `test_orchestrator_spec.py` (publish from the orchestrator is allowed, from its worker is refused naming it, a publish with no gate is refused, a non-writing orchestrator is not a writer); `packages/worker/tests/test_review.py` (the integration branch is shown and edited; the integrator's conflicts and failures).

## 4. Contract, schemas and docs
- [x] `specs/tech-stack.md`: update "Orchestrator (API contract)" (the Integration subsection, Output, Events, Writers, Compile and resume) and "Gate review" (an orchestrator's writer). Add decision-log rows: "Integration branch (6.3)", "Merge conflict (6.3)", and replace "Task writers (6.1)"'s "publishing waits for 6.3".
- [x] `specs/roadmap.md`: add a `[Plan](2026-11-09-integration-branch-merge/requirements.md)` link to row 6.3.
- [x] No schema, manifest or API type changes: the spec and the API models are unchanged (the new data is in events and the orchestrator's `data`).
- [x] `docs/`: no page covers orchestrator writers yet.
- [x] `CHANGELOG.md` `## [Unreleased]` entry.

## 5. Docker sandbox test
- [x] `packages/sandbox/tests/test_integrate.py` (docker-marked, as `test_docker_sandbox.py`): in a real clone, two task worktrees edit different files and merge cleanly into `agent/<run>/<orch>` with two merge commits; a third that edits the same lines conflicts and is reported with its path; the integration branch is left clean with no merge in progress; a second call merges nothing.
