# Validation: Writers' commits saved outside the sandbox

## Done when (from roadmap)
> A worker killed after a writer's commit resumes with that commit on its branch; deleting a running run's sandbox volume loses no completed step's commit

## Automated checks
- [ ] **Docker crash integration** (`packages/worker/tests/test_branches_docker.py`), the proof chosen for this phase:
  - [ ] a worker killed after a writer's commit is checkpointed: the next worker resumes the run, `branches_restored` names the branch, and `agent/<run>/writer` holds the same head commit as before the kill;
  - [ ] a run waiting at a gate whose sandbox volume is removed: on approval the run resumes on a fresh sandbox with the writer's commit on its branch, and the PR step would push it;
  - [ ] a running run whose sandbox (container and volume) is removed mid-step: no completed step's commit is lost once the run resumes;
  - [ ] the default branch moves on the remote between the kill and the resume: the resumed sandbox is at `runs.base_sha`, and the restored bundle applies.
- [ ] Store, sandbox and engine tests from plan groups 2 to 5 (base SHA set once, append-only versions, size cap, clone at a SHA, bundle import, saver called before the checkpoint, gate edits re-saved, no double merge after restore).
- [ ] Web: vitest for the event mapping; the console e2e step for the marker.
- [ ] Repo checks, run locally: `uv run ruff check`, `uv run mypy`, `uv run pytest` (with the Docker tests), and in `web/`: `pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.

## Manual / demo checks
- [ ] Start a docs run on the local stack, kill the worker (`docker compose kill worker`) once the writer step is done, start it again: the run resumes, the console's Activity shows the restore, and the PR step pushes the writer's commit.
- [ ] Console at 375 and 1440 px, light and dark: the "Commits saved" line on a writer step and on an orchestrator's integration, and a failed save's warning.

## Merge criteria
- [ ] Every check above passes locally (CI minutes are limited; CI is not watched).
- [ ] `specs/tech-stack.md` updated (Sandbox, events, decisions log, UI line) in the same PR.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] No credential in a bundle, an event or a log line: bundles hold repo commits only, and `test_no_secret_leak.py` still passes.
- [ ] Nothing is pushed to GitHub without its gate: no new push path.
