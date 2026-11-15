# Plan: A failed, cancelled or expired run keeps its code

Failing test first, as in 12.2: prove the gap, then backend, then console. Each group leaves the project green. Worker tests go in `packages/worker/tests/test_worker.py` beside 12.1's and 12.2's, run by name: never the whole `packages/sandbox/tests` (its sweep test removes the dev stack's sandboxes).

## 1. Prove the gap
- [x] `test_worker.py` (fake sandbox in the test's own directory; the Docker Done-when test comes with group 3): a writer commits, then the next step fails; assert the run's sandbox container and volume still exist and `runs.sandbox_kept_until` is set. `xfail(strict=True)` until group 3.
- [x] Same: a run cancelled while its writer has uncommitted edits; assert a `wip` version holds them (`xfail` until group 4).
- [x] Same: an expired approval's run keeps the sandbox it kept at the gate (`xfail`).

## 2. Policy and storage
- [ ] `agentic_api.workspaces.models`: `sandbox_ttl_s` (default 86,400, ceiling 259,200) and `branch_retention_days` (default 30, ceiling 90) in the platform policy, the workspace policy (`_lower_limit`) and `RunLimits`; settings page fields.
- [ ] Migration `0031_kept_sandboxes.py`: `runs.sandbox_kept_until`, `runs.sandbox_removed_at`; `run_branches.changes` (jsonb), `changes_error`, `bundle_removed_at`, `data` nullable, `kind` allows `wip`.
- [ ] `agentic_store`: `keep_sandbox(run, until)`, `expired_sandboxes` (`SKIP LOCKED`), `mark_sandbox_removed`, `request_sandbox_removal`, `kept_sandbox_run_ids`, `drop_old_bundles`; `save_branch` takes `changes`.
- [ ] Tests: migration up/down, limits and ceilings, the sweep query locks and skips, retention keeps rows and `changes`.

## 3. Keep and sweep in the worker
- [ ] `SandboxManager.exists(run_id)` (Docker: the container and volume by name; fake: the directory).
- [ ] `agentic_worker.main.AttemptSink`: before writing `run_failed` / `run_cancelled` of a run with a repo, snapshot uncommitted work (group 4) if the attempt has a sandbox open, else check `exists`; then `keep(run_id)` and add `sandbox_kept_until` (the event's time + the run's `sandbox_ttl_s`) to the payload. `_end_cancelled` and `_end_over_limit` no longer discard.
- [ ] `agentic_store.sink.summary_values`: an end event's `sandbox_kept_until` sets `runs.sandbox_kept_until`.
- [ ] Sweep task every `SANDBOX_SWEEP_S` (default 60): remove expired kept sandboxes (`discard`), `mark_sandbox_removed` with its `sandbox.removed` audit entry; then `drop_old_bundles`.
- [ ] Startup: `kept_sandbox_run_ids` joins `leased_run_ids | waiting_run_ids` in the orphan sweep's `keep`.
- [ ] Remove the group 1 `xfail` on the kept-sandbox and expiry tests.

## 4. Changes and uncommitted work
- [ ] `agentic_worker.branches.SandboxBranchSaver`: compute the branch's changes against `base_sha` with the `GateReview` code (same caps) and store them with the version; a failure to read them stores `changes_error`, the bundle is still saved.
- [ ] `agentic_sandbox.bundle.snapshot_worktree(worktree)`: temporary `GIT_INDEX_FILE`, `add -A`, `write-tree`, `commit-tree -p <tip>`, `update-ref refs/agentic/wip/<branch>`; nothing in the worktree or the branch changes.
- [ ] Worker, at a failed or cancelled end with a sandbox (`AttemptSink`, before the end event): snapshot each dirty writer worktree onto `wip/<run>/<key>` and save it as `kind: "wip"` (bundle `base..wip`, changes). A snapshot that fails is logged, never a failed end.
- [ ] Restore (12.2) ignores `wip` versions; test it.
- [ ] Remove the last `xfail`; tests for a clean worktree (no `wip`), untracked files, the caps.

## 5. API
- [ ] `GET /runs/{id}`: `sandbox` `{state, kept_until, removed_at}`; runs list unchanged.
- [ ] `GET /runs/{id}/changes`: latest version per branch with `changes`; `404` unknown run.
- [ ] `DELETE /runs/{id}/sandbox`: `202` when kept, `409` when running, none or already removed; audit `sandbox.remove_requested`.
- [ ] Regenerate the web's OpenAPI client; API tests for each.

## 6. Console
- [ ] `web/src/runs/`: the end event's `sandbox_kept_until` in the timeline; the run summary's `sandbox` drives the line.
- [ ] Header/failure summary: "Sandbox kept until" (`ExpiresIn`) with "Remove sandbox now" (confirm dialog, toast), or "Sandbox removed" (`RelativeTime`); a "Changes" action opening every writer's files.
- [ ] `saved-branches.tsx`: "View changes" per branch, "Includes uncommitted work" for `wip`, "Saved commits removed on …".
- [ ] Review sheet in a read-only mode (no edits, no Approve/Reject footer), fed by `GET /runs/{id}/changes`; `LoadingState`, `EmptyState`, `ErrorState`.
- [ ] Vitest for the line, the actions and the read-only sheet; a Playwright step in the console spec: a failed run on the fake sandbox shows "Sandbox kept until" and opens its changes.

## 7. Specs and docs
- [ ] `specs/tech-stack.md`: Sandbox (kept sandboxes), "Saved branches" (changes, `wip`, retention), run history contract (`sandbox`, `/changes`, `DELETE /sandbox`), audit actions, Run console lines, decisions-log rows (time to live, stored changes, `wip`, retention).
- [ ] `docs/operations/deployment.md`: `SANDBOX_SWEEP_S`, disk held by kept sandboxes.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
