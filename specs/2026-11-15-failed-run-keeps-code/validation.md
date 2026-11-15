# Validation: A failed, cancelled or expired run keeps its code

## Done when (from roadmap)
> A failed run's console shows what its writers changed and until when its sandbox is kept; once swept, the console says so and the changes are still shown

## Automated checks
- [ ] Worker (Docker backend, run by test name, never all of `packages/sandbox/tests`): a failed run keeps its sandbox with `sandbox_kept_until`; a cancelled run and an expired approval's run do too; a succeeded run's is removed; the sweep removes a kept sandbox past its time to live and logs `sandbox_removed`; the startup orphan sweep spares a kept one; "remove now" is done by the next sweep.
- [ ] Worker: a cancelled run's uncommitted edits (tracked and untracked) are a `wip` version with its changes; the worktree and branch are unchanged by the snapshot; a restore ignores `wip`.
- [ ] Store: migration 0031 up and down; `expired_sandboxes` locks and skips; retention nulls `data` and keeps `changes`; limits and ceilings for `sandbox_ttl_s` and `branch_retention_days`.
- [ ] API: `GET /runs/{id}` `sandbox` in each state; `GET /runs/{id}/changes`; `DELETE /runs/{id}/sandbox` `202` / `409` and its audit entry.
- [ ] Engine and store: the stored `changes` match the gate's shape and caps (50 files, 512 KB).
- [ ] Python: `ruff`, `pyright`, the package tests touched.
- [ ] Web: `pnpm lint && pnpm typecheck && pnpm test` (Vitest for the sandbox line, "Remove sandbox now", the read-only sheet and its three states).
- [ ] Web: `pnpm test:e2e` locally, with your OK to start the e2e stack, including the new failed-run step, `a11y.spec.ts` and `layout.spec.ts`.

## Manual / demo checks
- [ ] On the local stack, start a run whose writer commits and whose next step fails: the console says "Failed at …", "Sandbox kept until <time>", and "Changes" / "View changes" list the writer's files with their diff, read-only.
- [ ] Cancel a run while its writer is editing: "Uncommitted when the run ended" shows the edits.
- [ ] Set the workspace `sandbox_ttl_s` low (or "Remove sandbox now"): within `SANDBOX_SWEEP_S` the container and volume are gone (`docker ps -a`, `docker volume ls`), the console says "Sandbox removed", and the changes still open.
- [ ] Look at the console at 375 and 1440 px, light and dark.

## Merge criteria
- [ ] All checks above pass locally (CI minutes are limited: run them before pushing, don't watch CI).
- [ ] `specs/tech-stack.md` updated (Sandbox, Saved branches, run history, audit, Run console, decisions log) and the roadmap row marked done by the PR.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] No bundle bytes or file contents in logs; nothing pushed to GitHub by the new code.
