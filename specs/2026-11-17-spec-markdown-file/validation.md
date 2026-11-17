# Validation: Spec from a Markdown file

## Done when (from roadmap)
> An SDD run started from an uploaded spec file, with no Jira connection, opens a PR that implements it

## Automated checks
- [ ] **AC test** (worker, on the fake GitHub, no Atlassian connection in the workspace): `test_done_when_a_spec_file_run_opens_a_pr` starts `sdd-spec-file` with an uploaded spec through `POST /runs`, approves `approve_spec` and `approve_pr` through the API, and the run completes with a PR whose diff holds `specs/<slug>/spec.md`, `plan.md` and `tasks.md`, `<slug>` taken from the file's first heading
- [ ] **What agents receive** (engine, lessons rule 1, required by the repo): the spec writer's request holds the file between `<spec-file>` tags and reads `spec-input.md`; every later agent has it in its run context; no agent of the file flavour has a `jira` tool
- [ ] `sdd`'s existing tests (AC-5, 7.6 follow-up) pass unchanged
- [ ] Python lint, type check and tests green (`uv run`); `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e` (axe and layout screenshots) green, as `CLAUDE.md` requires for a web change

## Manual / demo checks
- [ ] **Real run with Claude (required, lessons rule 1):** in a workspace with Claude and GitHub but no Jira, start "Build from a spec file" from the New run sheet with an uploaded `.md` spec on a small real repo. In the console, read each step's Input and Activity: the spec writer read the file and the code and kept every requirement; the planner and tasker worked from the approved `spec.md`; the lead planned from `tasks.md`; the reviewer checked requirements by id. Approve both gates; the PR implements the spec and holds `specs/<slug>/`
- [ ] The same run started with "From the repo" and a path (`docs/spec.md`) shows the path as the source in Run context; a path that does not exist at the ref is refused on the field
- [ ] The New run sheet at 375 and 1440 px, light and dark: both choices are keyboard reachable, the file picker refuses a non-`.md` or oversized file before sending

## Merge criteria
- [ ] All checks above pass in CI
- [ ] tech-stack updated in this PR (input kind, `POST /runs` contract, `RunContext.spec`, `{spec}`, template section, decisions-log rows); the roadmap row links this plan
- [ ] `CHANGELOG.md` entry under `## [Unreleased]`
- [ ] The file's text appears in no log line; it reaches agents only as data in `<spec-file>` and through `reads`
