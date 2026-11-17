# Validation: SDD template

## Done when (from roadmap)
> AC-5

AC-5 (product spec, US-5): *Moving a Jira issue to the trigger status starts SDD; the issue receives spec, plan and PR links.*

## Automated checks
- [ ] **Template shape** (`packages/engine/tests`): the default spec validates, and the steps run in the order of `requirements.md`; `move` is present only with `move_to`; only `engineer` and `commit_specs` write; only `publish` publishes; every `jira.comment` and `jira.transition` is a tool node after a gate; `ask_jira`'s body is the artifact `post_questions` shows; bad options are refused (unpriced model, `max_passes` out of range)
- [ ] **What agents receive** (rule 1): on the fake runtime, the spec writer's request holds the issue brief; the planner and tasker read the spec *as edited at the gate*; the lead's input holds `tasks.md`; the reviewer reads `spec.md` and its tools read the integration branch; every agent's instructions start with what its input is
- [ ] **Engine run with `FakeAtlassian`**: with open questions, the questions comment is posted after its gate; without them, `clarify` runs nothing; the final comment holds working spec, plan, tasks and PR links made by the platform; the issue moves to `move_to`; a step re-run after a crash posts nothing twice
- [ ] **`repo.commitArtifacts`**: the files land on the integration branch under `specs/<KEY>-<slug>/` and appear in `approve_pr`'s `changes`; path escapes are refused; validation of writer ordering
- [ ] **`links` on `jira.comment`**: resolution from the publish result and the commit step; `reference` for a source that is not before the comment
- [ ] **Manual start**: `POST /runs` with `input.kind: "jira_issue"` sets `jira_issue` and the agents get the brief; `issue_invalid`, `site_required` and `project_not_allowed` are refused with `422`
- [ ] **Webhook to PR** (API + worker): a signed fake delivery starts `sdd`, approvals via the API lead to an opened PR with the spec files, then a posted comment and a recorded move; rejecting `approve_spec` ends the run `completed` with nothing pushed
- [ ] Router `default: null` (if adopted): engine tests plus the web's graph-op and port-check fixtures
- [ ] `uv run` lint, type check and tests green; `cd web && pnpm lint && pnpm typecheck && pnpm test` for the start-sheet label; CI green

## Manual / demo checks
- [ ] **Real run with Claude (required):** on a real Jira site and GitHub repo, create a trigger rule (project, status "Ready for dev", template `sdd`, the repo); move an issue that has mapped acceptance criteria to that status. In the console, read each step's Input and Activity: the spec writer read the issue and the code, and the spec keeps the acceptance criteria; the planner and tasker read the approved spec; the lead planned from `tasks.md`; the reviewer checked the requirements by id. Approve the gates. The issue gets a comment with spec, plan, tasks and PR links that open the right files, and moves to `move_to`
- [ ] The same issue started by hand from the New run sheet (input `PROJ-12`) shows the issue brief in the first step's Run context
- [ ] An issue with a vague description: the questions gate shows `[NEEDS CLARIFICATION]` items, they reach Jira after approval, and rejecting the spec gate ends the run completed
- [ ] The PR's `specs/<KEY>-<slug>/` holds `spec.md`, `plan.md` and `tasks.md` in Spec Kit's layout

## Merge criteria
- [ ] All checks above pass in CI
- [ ] tech-stack updated (SDD template, Jira tools `links`, `repo.commitArtifacts`, Router change, manual brief) with decision-log rows; roadmap row links this plan
- [ ] `CHANGELOG.md` entry under `[Unreleased]`
- [ ] Any surprise from the real run recorded in `specs/lessons.md` with its rule
- [ ] No token, issue text or secret in logs (existing `test_jira_tokens_appear_nowhere` still green)
