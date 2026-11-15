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
- **Keep the sandbox** of a run that ends `failed` or `cancelled` (cancel request, expired approval, a policy stop) when it has one. The worker's `AttemptSink` acts just before it writes the run's end event: it saves uncommitted work (below), keeps the sandbox, and adds `sandbox_kept_until` (the end + `sandbox_ttl_s`) to the end event's payload, which the event sink copies to `runs.sandbox_kept_until` in the same transaction. The end event stays the run's last event, and a client that refetches the run on it already sees the sandbox kept. A succeeded run's sandbox is removed as today. A run cancelled while queued or waiting keeps the sandbox it kept at a gate, if one exists (`SandboxManager.exists`).
- **Policy limit `sandbox_ttl_s`:** workspace default 24 h, platform ceiling 72 h, in `RunLimits` and the workspace policy, fixed on the run when it ends (a later policy change never moves a kept sandbox's expiry).
- **Sweep:** every worker runs `agentic_store.expired_sandboxes` every `SANDBOX_SWEEP_S` (default 60 s): runs past `sandbox_kept_until` with no `sandbox_removed_at` are locked (`SKIP LOCKED`), their sandbox removed (`discard`), `sandbox_removed_at` set and a `sandbox.removed` audit entry written. The startup orphan sweep spares runs whose sandbox is still kept.
- **Remove now:** "Remove sandbox now" on a run with a kept sandbox (confirm dialog). `DELETE /runs/{id}/sandbox` sets `sandbox_kept_until` to now and answers `202`; the next worker sweep removes it (only workers touch Docker). Audit `sandbox.remove_requested`.
- **Changed files stored at save:** with each `run_branches` version the worker also stores the branch's changes against the run's base in the gate's `changes` shape and caps (`run_branches.changes` jsonb, `changes_error`), so they are shown without git in the API and after the sandbox is gone.
- **Uncommitted work:** when a run fails or is cancelled with a sandbox, the worker snapshots each writer worktree that has uncommitted changes (tracked and untracked) as one commit on top of its branch's tip, without touching the worktree, its index or its branch (a temporary index, `write-tree`, `commit-tree`), on the branch `wip/<run>/<key>`. It is saved as a `wip` version (bundle and changes against the run's base, so it shows the branch as it was on disk when the run ended). `wip/` is outside `agent/`, so a restore, an integration and `openPR` never see it, and it is never pushed.
- **Bundle retention:** workspace limit `branch_retention_days`, default 30, ceiling 90. The same worker sweep nulls `run_branches.data` of finished runs older than it and sets `bundle_removed_at`; the rows and their `changes` stay. Such a run cannot be restored from (12.4 will say so).
- **API:** `GET /runs/{id}` gains `sandbox` `{state: "running" | "kept" | "removed" | "none", kept_until, removed_at}`. `GET /runs/{id}/changes`: the latest version of each saved branch, `{node_id, key, branch, kind ("writer" | "integration" | "wip"), version, head, commits, saved_at, changes, changes_error, bundle_removed_at}`.
- **Log:** no new run events, since the end event stays last. `run_failed` / `run_cancelled` carry `sandbox_kept_until`; removals happen after the end, so they go to the audit log: `sandbox.removed` (actor `system`, with the `kept_until` it was removed at; a `sandbox.remove_requested` entry before it says a person asked) and `sandbox.remove_requested`. A `wip` save is a `run_branches` row, not an event.
- **Console:**
  - A failed or cancelled run has a sandbox line under the banner (`RunSandboxLine`): "Sandbox kept" with `ExpiresIn`, "View changes" and "Remove sandbox now" (confirm dialog); "Sandbox being removed" once its time is up or a removal was asked (the run is read again every 15 s until it is); "Sandbox removed" with `RelativeTime`, "what the writers changed is still saved" and "View changes". On the line rather than in the failure banner, so a cancelled run, which has no banner, gets it too.
  - Each branch in a step's "Commits saved" (12.2) has "View changes", for that writer alone.
  - "View changes" opens the review sheet read-only (`RunChangesSheet`), from `GET /runs/{id}/changes`: one writer at a time, with a "Writer" picker when there are several; a writer's `wip` version stands for its branch and reads "includes uncommitted work"; "Its saved commits were removed …" once the bundle is gone. Loading, empty ("No writer changed a file.") and error (Retry) states.
  - Settings, Run limits: "Keep a failed run's sandbox (hours)" and "Keep saved commits (days)", checked against the API's `ceilings`.

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
| Uncommitted work | A `wip` version per dirty writer worktree at run end, on `wip/<run>/<key>`, via a temporary index and `commit-tree` | Saves the failing step's edits without touching the worktree or the branch's history; outside `agent/`, so nothing restores, merges or pushes it; 12.4 can choose to use it. |
| Where the keep is recorded | In the end event's payload (`sandbox_kept_until`), added by the worker's `AttemptSink` before it writes it | The end event stays the run's last, and status and expiry change in one transaction, so the console never shows a failed run without its sandbox line. Removals come later and go to the audit log. |
| Bundle retention | `branch_retention_days` (default 30, ceiling 90) drops the bundle bytes only; rows and `changes` stay | The roadmap row says changes are still shown after the sweep; disk for bundles stays bounded. |
| Remove now | `DELETE /runs/{id}/sandbox` → `202`, the sweep removes | Keeps Docker in the workers; done within `SANDBOX_SWEEP_S`. |
| Real run with Claude (lessons rule 1) | Not required | Agents' instructions, inputs and tools do not change. |

## Open questions
- None. To check during the build: whether a run cancelled while its step is mid-commit snapshots a half-written worktree cleanly (the snapshot reads the files as they are; the test in plan group 1 covers a cancel mid-step).
