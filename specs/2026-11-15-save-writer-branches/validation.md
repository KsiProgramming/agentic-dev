# Validation: Writers' commits saved outside the sandbox

## Done when (from roadmap)
> A worker killed after a writer's commit resumes with that commit on its branch; deleting a running run's sandbox volume loses no completed step's commit

## Automated checks
- [x] **Docker crash integration** (`packages/worker/tests/test_worker.py`), the proof chosen for this phase:
  - [x] a worker killed after a writer's commit is checkpointed: the bundle is in `run_branches` before the next worker starts; the next worker resumes the run, `branches_restored` names the branch before `run_resumed`, and `agent/<run>/writer` holds the writer's commit (`test_done_when_a_killed_worker_s_run_resumes_with_its_writer_s_commit`);
  - [x] a run waiting at a gate whose sandbox container and volume are removed: on approval the run resumes on a fresh sandbox with the writer's commit on its branch (`test_done_when_a_waiting_run_whose_sandbox_was_removed_keeps_its_writer_s_commit`);
  - [x] a running run whose sandbox is removed mid-step: the completed steps' commits are in `run_branches` (shown by the first test, whose bundle is stored before the worker goes); the run itself is not resumed automatically (requirements, open questions);
  - [x] the default branch moves on the remote between the kill and the resume: the resumed sandbox is at `runs.base_sha`, and the restored bundle applies (`test_a_resumed_run_works_on_its_base_commit_after_the_branch_moved_on`, fake backend).
- [x] Store, sandbox and engine tests from plan groups 2 to 5 (base SHA set once, append-only versions, size cap, clone at a SHA, bundle import on both backends, saver called before the checkpoint, gate saved once decided, no double merge after restore).
- [x] Web: vitest for the event mapping, the summaries and the "Commits saved" section. No e2e step: see below.
- [ ] Repo checks, run locally: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` per package (the sandbox package by file, never its sweep test, which removes every sandbox on the host), and in `web/`: `pnpm lint && pnpm typecheck && pnpm test`; `pnpm test:e2e` only with the user's OK, on their stack in fake mode.

## Manual / demo checks
- [ ] Start a docs run on the local stack, kill the worker (`docker compose kill worker`) once the writer step is done, start it again: the run resumes, the console's Raw events show "1 saved branch restored into a fresh sandbox", the writer step shows "Commits saved", and the PR step pushes the writer's commit.
- [ ] Console at 375 and 1440 px, light and dark: the "Commits saved" line on a writer step and on an orchestrator's integration, and a failed save's warning.

## Merge criteria
- [ ] Every check above passes locally (CI minutes are limited; CI is not watched).
- [ ] `specs/tech-stack.md` updated (Sandbox, events, decisions log, UI line) in the same PR.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] No credential in a bundle, an event or a log line: bundles hold repo commits only, and `test_no_secret_leak.py` still passes.
- [ ] Nothing is pushed to GitHub without its gate: no new push path.
