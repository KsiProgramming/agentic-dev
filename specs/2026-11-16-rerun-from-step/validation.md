# Validation: Rerun from a step

## Done when (from roadmap)
> A run that failed at its last step is rerun from that step with changed instructions; the earlier steps do not run again, and the new run's branches hold the code they held at that step

## Automated checks
- [x] Engine (fake runtime): rerun from the last of three steps runs only that step; no `node_started` or usage events for the earlier steps in the new run; the new run's cost is the last step's only.
- [x] Engine: rerun from a container step (an orchestrator) runs it whole; a gate step pauses again; a seeded rerun cut off resumes from its own checkpoint. (Router choices carried: not tested yet.)
- [x] Engine, "what the agent receives" (lessons rule 1): the rerun step's request has the edited instructions, the earlier steps' outputs as input, and the run's request and repo context. (That its tools read the restored branch is the worker's Docker test.)
- [x] Engine: a step that is not top-level, or was never reached, is refused.
- [x] Store (Testcontainers): migration 0032 up and down; `run_branches.step` saved by every step kind that commits; `branches_before` returns the versions as of the step, not later ones, and skips `wip` and dropped bundles.
- [x] Worker (fake sandbox, one Docker test; never all of `packages/sandbox/tests`): the new run's `agent/<new run>/*` branches hold the original's commits as of the step; `use_wip` restores the writer's branch with 12.3's snapshot commit on top; a killed worker of a seeded run resumes from the new run's own checkpoint without re-seeding.
- [x] API: `from` happy path; `422` unknown or nested node, a parameter `setParam` refuses; `409` not ended, not reached, bundles dropped, saved before 12.4, no `wip` for `use_wip`; the original run unchanged; audit `run.rerun` with `from_node`, `use_wip`, edited paths and no values.
- [x] Python: `ruff`, `pyright`, the package tests touched (the checkpoint copy on the Postgres saver, `test_checkpoint.py`, runs in CI: psycopg needs a selector loop, which Windows lacks).
- [x] Web: `pnpm lint && pnpm typecheck && pnpm test` (Vitest for the action and the sheet).

## Manual / demo checks
- [x] Real run, `AGENTIC_RUNTIME=claude`, on `KsiProgramming/agentic-dev` (2026-11-16). Run `21014c9f`: the writer read the engine package and committed `docs/RERUN_DEMO.md` (`7636101b`); the reviewer, given a typed input port, failed at it ("input of 'reviewer' (from 'writer') is not JSON"); $0.078. Rerun `c0b53421` from `reviewer`, editing its instructions and clearing `input_schema`: `branches_restored` gave back `agent/c0b53421/writer` at `7636101b`, `run_started` carried `["writer"]`, only the reviewer ran ($0.011), it followed the new instructions (read `packages/engine/pyproject.toml`) and named the writer's file from its carried input, and the new run's saved branch and changes match the original's, on the same base `0bc91ef6`. Read step by step in the events. The reviewer could not read the file itself: read-only steps read the base checkout, not a writer's branch, until 13.1.
- [ ] Same run with `use_wip` on a run cancelled mid-edit (covered by the store and API tests; not run with Claude).
- [x] On the console: "Rerun of <id8> from <step>" in the header, the carried steps above the step list, "Rerun from here" in the step header and its sheet, at 375 and 1440 px, light and dark (screenshots). The Steps tile counts the steps the rerun ran ("1 of 2"), not the carried one.

## Merge criteria
- [x] All checks above pass locally; `pnpm test:e2e` ran locally on the fake stack (291 passed; the 10 that failed in the parallel run pass with `--workers=1`, and `ac2` and `kept-sandbox` were fixed).
- [ ] `specs/tech-stack.md` updated (rerun contract, Saved branches, Run console, audit, decisions log) and the roadmap row marked done by the PR.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [x] The real Claude run read step by step; nothing tests missed (no `lessons.md` entry).
- [ ] No bundle bytes, parameter values or secrets in logs or audit entries; nothing pushed to GitHub by the new code.
