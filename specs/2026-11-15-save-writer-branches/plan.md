# Plan: Writers' commits saved outside the sandbox

Crash test first, as the roadmap row asks: prove the gap, then close it. Each group leaves the project green.

## 1. Prove the gap
- [ ] `packages/worker/tests/test_branches_docker.py` (Docker backend, marked like `test_audit_docker.py`): a two-node run (writer, then a gate), the worker killed after the writer's commit is checkpointed, a second worker resumes it; assert `agent/<run>/writer` holds the writer's commit. Mark it `xfail(strict=True)` until group 5.
- [ ] Same file: a run waiting at its gate whose sandbox volume is removed, then approved; assert the writer's commit is still on its branch (`xfail` too).
- [ ] Find out and write down in the test what happens when a running attempt's container and volume are removed mid-step (requirements, open question). If the run fails, add a test that it resumes on a fresh sandbox, and a task in group 5 to make it so.

## 2. Pin the run's base commit
- [ ] Migration `0030_run_branches.py` (part 1): `runs.base_sha` (nullable, 40 hex).
- [ ] `agentic_sandbox.source.clone_shallow`: clone at an exact SHA (`git fetch --depth 1 origin <sha>`, and the same for a local path); a SHA that is gone fails with a clear `SandboxError`.
- [ ] `DockerSandboxManager.open` and `FakeSandboxManager`: return or expose the clone's `HEAD`; the worker records it in `runs.base_sha` on first clone (`agentic_store.runs`) and passes it as the ref on every later clone.
- [ ] Tests: `test_source.py` (clone at a SHA after the remote branch moved on), a store test that `base_sha` is set once and never overwritten.

## 3. Store saved branches
- [ ] Migration 0030 (part 2): `run_branches` (`run_id`, `branch`, `node_key`, `kind`, `version`, `base_sha`, `head_sha`, `commits`, `size`, `data bytea`, `created_at`; unique `(run_id, branch, version)`).
- [ ] `packages/store/src/agentic_store/branches.py`: `save_branch` (new version only if `head_sha` changed, in one transaction with its `branch_saved` event), `latest_branches(run_id)`; refuse a bundle over 64 MB.
- [ ] `agentic_engine.events`: `BRANCH_SAVED`, `BRANCH_SAVE_FAILED`, `BRANCHES_RESTORED`, with their payload models.
- [ ] Tests: append-only versions, unchanged head adds nothing, latest per branch, size cap.

## 4. Save from the engine
- [ ] `agentic_engine.branches`: `BranchSaver` protocol, `save(node_key, branch, kind)`, injected like `BranchIntegrator`; the fake runtime's tests get an in-memory saver.
- [ ] `compile.py`: call it at the end of a writer node, a map item and a parallel branch that wrote, an orchestrator task's writer, and `<id>.integrate`, **before** the update is returned; a failed save emits `branch_save_failed` and the step still completes.
- [ ] `packages/worker/src/agentic_worker/branches.py`: `SandboxBranchSaver` over `agentic_sandbox.bundle` (export with the pinned base) and `agentic_store.branches`.
- [ ] `review.py`: after `Edit at gate` commits, save each edited writer's branch again.
- [ ] Engine tests: the saver is called for every writer kind and the integration branch, before the node's checkpoint; a writer with no commits is not saved; gate edits trigger a save.

## 5. Restore on a fresh sandbox
- [ ] `agentic_sandbox.bundle`: `import_bundle(sandbox, branch, data)` fetches the bundle into the checkout's `.git` as `refs/heads/<branch>` (branch name checked against `BRANCH_PATTERN`).
- [ ] Worker attempt start (`main.py`, where `open(..., reuse=...)` is called): when the sandbox is fresh and the run has saved branches, import the latest of each before the graph resumes; emit `branches_restored`. A reused kept sandbox is left as it is.
- [ ] The mid-step lost-sandbox path from group 1, if it needs a change.
- [ ] Remove the `xfail` marks from group 1; add a test that a resumed orchestrator merges on top of its restored integration branch without merging twice (6.3's "merging twice" rule).

## 6. Console marker
- [ ] `web/src/runs/`: read `branch_saved`, `branch_save_failed` and `branches_restored` from the event stream.
- [ ] Writer step and integration Output: a "Commits saved" line (commit count, `IdChip` head commit, `RelativeTime`); a failed save as a warning with its reason. Built from existing display and state components.
- [ ] Activity: one line for `branches_restored` on a resumed attempt.
- [ ] Vitest for the event mapping; an e2e step in the existing console spec that sees the marker.

## 7. Specs and docs
- [ ] `specs/tech-stack.md`: Sandbox section (pinned base, saved branches, restore), the three events in the events contract, decisions-log rows (bundles in Postgres, pinned base, save before checkpoint, size cap), UI design system line for the marker.
- [ ] Docker backend module docstring: a fresh sandbox now restores saved branches.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
