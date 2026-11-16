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
- [ ] Real run, `AGENTIC_RUNTIME=claude`, on a real repo: a workflow whose writer commits in step 1 and whose last step fails (for example a reviewer with instructions that make it fail). In the console, "Rerun from here" on the last step, change its instructions, Start. Read the new run step by step in Activity: step 1 is carried over and not run; the last step received the new instructions, read the writer's code on its restored branch, and succeeded; the cost shown is the last step's only.
- [ ] Same run with `use_wip` on a run cancelled mid-edit: the writer starts with its earlier uncommitted edits as one commit.
- [ ] On the console: "Rerun of <id8> from <step>" in the header and the runs list; carried steps link to the original; at 375 and 1440 px, light and dark.

## Merge criteria
- [ ] All checks above pass locally (CI minutes are limited: run them before pushing, don't watch CI); `pnpm test:e2e` (axe and layout) run locally with your OK to start the e2e stack.
- [ ] `specs/tech-stack.md` updated (rerun contract, Saved branches, Run console, audit, decisions log) and the roadmap row marked done by the PR.
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] The real Claude run read step by step, with anything tests missed added to `lessons.md`.
- [ ] No bundle bytes, parameter values or secrets in logs or audit entries; nothing pushed to GitHub by the new code.
