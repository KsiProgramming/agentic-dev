# A failed, cancelled or expired run keeps its code

Roadmap phase: 12.3
Branch: plan/12.3-failed-run-keeps-code

## Context

12.2 saves each writer's and each integration branch as a `git bundle` in Postgres (`run_branches`) when its step completes, and restores them into a fresh sandbox. But a run that ends `failed` or `cancelled` (an expired approval included) still has its sandbox removed as soon as `DockerSandboxManager.open` exits (`packages/sandbox/src/agentic_sandbox/docker_backend.py`), and the console shows nothing of what its writers changed: "Commits saved" lists branches and tips, not files. The work of the failing step itself, not yet committed, is lost with the sandbox. So principle 9 ("Nothing is lost") still fails for the code of a run that did not succeed.

12.3 keeps that sandbox for a time to live, sweeps it after, and shows the writers' changes from data that outlives both the sandbox and, later, the bundles. 12.4 (rerun from a step) builds on the saved bundles and on the uncommitted work saved here.

Specs it follows:
- Mission principle 9 (nothing is lost) and 8 (numbers are truthful; a thing nobody acts on expires instead of waiting forever, as approvals do).
- Mission principle 3: keeping and saving are not a push. Nothing leaves for GitHub.
- Mission principle 6: keeping, sweeping and removing a sandbox are events in the append-only log and audit entries.
- Tech stack, Approval expiry (11.3): a time to live is a policy limit with a platform ceiling, turned into action by a sweep in every worker (`SKIP LOCKED`), never by the API. Same model here.
- Tech stack, Gate review: the `changes` shape (status, `before`/`after`, 50-file / 512 KB caps) and the read-only review sheet are reused for a writer's changes.
- Tech stack, Saved branches (12.2): `run_branches`, `SandboxBranchSaver`, `list_saved_branches` ("for 12.3").

## Scope

### In scope
- **Keep the sandbox** of a run that ends `failed` or `cancelled` (cancel request, expired approval, a policy stop) when it had one. The worker keeps it instead of removing it and records `runs.sandbox_kept_until` (end + `sandbox_ttl_s`). A succeeded run's sandbox is removed as today. A run cancelled while queued or waiting at a gate keeps the sandbox it kept at the gate, if any.
- **Policy limit `sandbox_ttl_s`:** workspace default 24 h, platform ceiling 72 h, in `RunLimits` and the workspace policy, fixed on the run when it ends (a later policy change never moves a kept sandbox's expiry).
- **Sweep:** every worker runs `agentic_store.expired_sandboxes` every `SANDBOX_SWEEP_S` (default 60 s): runs past `sandbox_kept_until` with no `sandbox_removed_at` are locked (`SKIP LOCKED`), their sandbox removed (`discard`), `sandbox_removed_at` set, `sandbox_removed` logged and a `sandbox.removed` audit entry written. The startup orphan sweep spares runs whose sandbox is still kept.
- **Remove now:** "Remove sandbox now" on a run with a kept sandbox (confirm dialog). `DELETE /runs/{id}/sandbox` sets `sandbox_kept_until` to now and answers `202`; the next worker sweep removes it (only workers touch Docker). Audit `sandbox.remove_requested`.
- **Changed files stored at save:** with each `run_branches` version the worker also stores the branch's changes against the run's base in the gate's `changes` shape and caps (`run_branches.changes` jsonb, `changes_error`), so they are shown without git in the API and after the sandbox is gone.
- **Uncommitted work:** when a run fails or is cancelled with a sandbox, the worker snapshots each writer worktree that has uncommitted changes (tracked and untracked, without touching the worktree or the branch: a temporary index, `write-tree`, `commit-tree` on the branch tip, under `refs/agentic/wip/<branch>`) and saves it as a `wip` version of that branch, with its changes. It is never restored into a branch and never pushed.
- **Bundle retention:** workspace limit `branch_retention_days`, default 30, ceiling 90. The same worker sweep nulls `run_branches.data` of finished runs older than it and sets `bundle_removed_at`; the rows and their `changes` stay. Such a run cannot be restored from (12.4 will say so).
- **API:** `GET /runs/{id}` gains `sandbox` `{state: "running" | "kept" | "removed" | "none", kept_until, removed_at}`. `GET /runs/{id}/changes`: the latest version of each saved branch, `{node_id, key, branch, kind ("writer" | "integration" | "wip"), version, head, commits, saved_at, changes, changes_error, bundle_removed_at}`.
- **Events:** `sandbox_kept` `{until}` (run-level, before `run_failed` / `run_cancelled`), `sandbox_removed` `{reason: "expired" | "requested"}`, `branch_saved` with `kind: "wip"`.
- **Console:**
  - A failed or cancelled run's header says "Sandbox kept until <time>" (`ExpiresIn`) with "Remove sandbox now", or "Sandbox removed <time>" (`RelativeTime`) once swept.
  - Each writer and orchestrator step's "Commits saved" (12.2) gains "View changes", which opens the review sheet read-only; uncommitted work reads "Uncommitted when the run ended" beside it. "Saved commits removed on …" when the bundle is gone.
  - A run-level "Changes" entry in the failure summary opens the same sheet with every writer's files.
  - Loading, empty ("No writer changed a file") and error states.

### Out of scope
- Rerun from a step with the code restored, and restoring `wip` work: **12.4**.
- Opening a kept sandbox interactively (a shell, a file browser): not planned.
- Keeping the sandbox of a succeeded run: its work is in the PR.
- Pushing anything to GitHub: never, by principle 3.
- Showing `base_sha` in the console.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Which runs keep their sandbox | `failed` and `cancelled` (expired approvals and policy stops included) | Those are the runs whose code is not in a PR. |
| Time to live | Policy limit `sandbox_ttl_s`, default 24 h, ceiling 72 h, fixed when the run ends | Same model as approval expiry (11.3); a day to look at a failure without many idle volumes. |
| Who removes | A sweep in every worker; the API only moves `sandbox_kept_until` | Only workers touch Docker and write run events (11.3, 12.1). |
| How changes are shown after the sweep | Stored with each saved version, in the gate's `changes` shape and caps | The API has no git and no clone; the bundle alone cannot be diffed without its base. Reuses the review sheet read-only. |
| Uncommitted work | A `wip` version per dirty writer worktree at run end, via a temporary index and `commit-tree` | Saves the failing step's edits without touching the worktree or the branch's history; 12.4 can choose to use it. |
| Bundle retention | `branch_retention_days` (default 30, ceiling 90) drops the bundle bytes only; rows and `changes` stay | The roadmap row says changes are still shown after the sweep; disk for bundles stays bounded. |
| Remove now | `DELETE /runs/{id}/sandbox` → `202`, the sweep removes | Keeps Docker in the workers; done within `SANDBOX_SWEEP_S`. |
| Real run with Claude (lessons rule 1) | Not required | Agents' instructions, inputs and tools do not change. |

## Open questions
- None. To check during the build: whether a run cancelled while its step is mid-commit snapshots a half-written worktree cleanly (the snapshot reads the files as they are; the test in plan group 1 covers a cancel mid-step).
