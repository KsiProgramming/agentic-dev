# Plan: Writers' commits saved outside the sandbox

Crash test first, as the roadmap row asks: prove the gap, then close it. Each group leaves the project green. The crash tests live in `packages/worker/tests/test_worker.py`, beside 12.1's, to reuse its worker helpers.

## 1. Prove the gap
- [x] `test_worker.py` (Docker backend): a writer then a reviewer, the worker stopped after the writer's commit is checkpointed, a second worker resumes it; assert `agent/<run>/writer` holds the writer's commit. `xfail(strict=True)` until group 5.
- [x] Same file: a run waiting at its gate whose sandbox container and volume are removed, then approved; assert the writer's commit is still on its branch (`xfail` too).
- [x] Find out what happens when a running attempt's sandbox is removed mid-step: the step's tool calls fail; no automatic resume (requirements, open questions; left for a later phase).

## 2. Pin the run's base commit
- [x] Migration `0030_run_branches.py` (part 1): `runs.base_sha` (nullable, 40 hex).
- [x] `agentic_sandbox.source.clone_shallow(..., at=)`: clone, then fetch the SHA at depth 1 and reset to it when the branch moved on; a SHA that is gone fails with a clear `SandboxError`.
- [x] `DockerSandboxManager.open` and `FakeSandboxManager` take `at` and `restore`; the worker reads the clone's `HEAD` (`branch_heads`), records it in `runs.base_sha` on first clone (`record_base_sha`) and passes it as `at` on every later clone.
- [x] Tests: `test_source.py` (clone at a SHA after the remote branch moved on, a gone SHA, a non-SHA), a store test that `base_sha` is set once and never overwritten.

## 3. Store saved branches
- [x] Migration 0030 (part 2): `run_branches` (`run_id`, `branch`, `node_key`, `kind`, `version`, `base_sha`, `head_sha`, `commits`, `size`, `data bytea`, `created_at`; unique `(run_id, branch, version)`).
- [x] `packages/store/src/agentic_store/branches.py`: `save_branch` (new version only if `head_sha` changed; the engine logs `branch_saved` after it), `latest_branches`, `list_saved_branches`; refuse a bundle over 64 MB.
- [x] `agentic_engine.events`: `BRANCH_SAVED`, `BRANCH_SAVE_FAILED`, `BRANCHES_RESTORED`; payload models in `agentic_engine.branches`.
- [x] Tests: append-only versions, unchanged head adds nothing, latest per branch, size cap.

## 4. Save from the engine
- [x] `agentic_engine.branches`: `BranchSaver` protocol, `save()` (every moved branch), injected like `BranchIntegrator`; engine tests use a recording saver.
- [x] `compile.py`: `_saving` wraps agent, tool and gate steps, map items, parallel branches, orchestrator tasks and `<id>.integrate`, saving **before** the update is returned; a failed save emits `branch_save_failed` and the step still completes.
- [x] `packages/worker/src/agentic_worker/branches.py`: `SandboxBranchSaver` over `agentic_sandbox.bundle` and `agentic_store.branches`.
- [x] Gate edits: the gate step is wrapped like the others, so the `Edit at gate` commits are saved when it ends (no change to `review.py`).
- [x] Engine tests (`test_branch_saves.py`): the saver is called after steps, map items, branches, tasks and integration, before the checkpoint; a gate saves once decided, not when it pauses; a broken saver does not fail the step.

## 5. Restore on a fresh sandbox
- [x] `agentic_sandbox.bundle.import_bundles(clone, bundles)` fetches each bundle into the clone on the worker as `refs/heads/<branch>` (names checked against `BRANCH_PATTERN`).
- [x] Worker attempt start (`main.py`): pass the latest saved branches as `restore`; the manager fetches them only into a fresh sandbox; the worker logs `branches_restored` when `Sandbox.restored` is not empty.
- [x] The mid-step lost-sandbox path: no change in 12.2 (see requirements).
- [x] Remove the `xfail` marks from group 1; `test_integrate.py`: a restored integration branch merges nothing twice; `test_worker.py`: a resumed run works on its base commit after the branch moved on.

## 6. Console marker
- [x] `web/src/runs/`: `EVENT_TYPES` lists the three events (and the 6.x ones it missed); the timeline keeps each step's `savedBranches`.
- [x] Writer step and orchestrator Output: "Commits saved" (`saved-branches.tsx`: branch, commit count, `IdChip` tip, `RelativeTime`); a failed save as an `ErrorLine`.
- [x] Raw events: one line each for the three events (`summarizePayload`); the Activity tab is per step.
- [x] Vitest for the event mapping and the section (`saved-branches.test.tsx`). An e2e step is not added: the e2e stack runs on the fake sandbox and needs the user's OK to run (see validation).

## 7. Specs and docs
- [x] `specs/tech-stack.md`: Sandbox section, a "Saved branches (12.2)" contract section with the events, three decisions-log rows, the Run console Output line.
- [x] Docker backend and worker module docstrings: a fresh sandbox now restores saved branches.
- [x] `CHANGELOG.md` entry under `## [Unreleased]`.
