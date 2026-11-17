# Plan: SDD template

Engine and tools first, then the template, then the end-to-end proof. The project stays green after each group. Read `specs/lessons.md` before groups 1 to 4.

## 1. Contracts in the specs
- [ ] Settle the four open questions in `requirements.md` (router skip, marker test, link form, slug) and record each in the decisions log
- [ ] `tech-stack.md`: an "SDD template" section. Extend "Jira tools" (`links` on `jira.comment`), "Router" (`default: null` if chosen), and add `repo.commitArtifacts` to "Tool layer"; extend "The Jira issue (7.4)" for manual starts (`input.kind: "jira_issue"`)
- [ ] `schemas/`: regenerate the workflow JSON Schema after the spec model changes

## 2. Issue brief for runs started by hand
- [ ] Spec: `input.kind` (`"text"` default | `"jira_issue"`) on the workflow input model (`packages/engine/.../spec`)
- [ ] API `create_run` and rerun: for `kind: "jira_issue"`, check that the input is one issue key (`issue_invalid`), resolve the site (`site_required` / `site_unknown`) and the project (`project_not_allowed`), then set `runs.jira_issue`; a trigger-started run is unchanged
- [ ] Tests: `packages/api/tests` (manual run gets `jira_issue`, the refusals); worker test that a manual run's agents receive the brief (rule 1)
- [ ] Web: the New run sheet labels a `jira_issue` input "Jira issue" with the key as placeholder and validates the key's form (no new component)

## 3. Commit artifacts onto a writer's branch
- [ ] `repo.commitArtifacts {into, dir, files}` in `agentic_tools.repo` (write tools), committing on `into`'s branch through the engine's integrator / `RepoTools` routing (key = the orchestrator's id)
- [ ] `dir` placeholder `{issue}` (`<KEY>-<slug>`) resolved by the engine from the brief, else the request; path checks (stays under the repo, no `..`, no `.git`)
- [ ] Validation: a writer for `into` (gate and publish ordering, `not_allowed_in_*` like other writers); `artifact_unknown` for files no step writes before it
- [ ] Gate review: the committed files appear in the gate's `changes` under the orchestrator's key
- [ ] Engine tests (fake runtime + fake integrator) and a sandbox test that the commit lands on the integration branch

## 4. Platform-made links on `jira.comment`
- [ ] Spec: `links` on the `jira.comment` tool node (`{label: {pr: <publisher>} | {committed: <step>, artifact: <name>}}`)
- [ ] Engine: resolve after the named steps ran (the publisher's PR URL from its result; file links from the commit step's paths and the PR), append as a Markdown list under the body; the tool never sees sources
- [ ] Validation: sources name earlier steps (`reference`); a comment after a publish is covered by the gate before the publish (adjust `jira_write_issues` if it does not already allow it)
- [ ] Router `default: null` (skip) if chosen in group 1, with tests and the web's graph-op and port mirrors (`schemas/fixtures`)
- [ ] Tests: resolution, a crash between publish and comment does not post twice (7.2's `created: false`), validation cases

## 5. The `sdd` template
- [ ] `agentic_engine/templates/sdd.py` with `SddParams`; register it in `templates/__init__.py`; default spec in `packages/engine/tests/fixtures/specs/valid/sdd.json`
- [ ] Instructions per the "Rules for writing workflows and templates" in lessons: each agent states its input, read tools for every checker, issue text is data, Spec Kit layouts for `spec.md` and `tasks.md`, the reviewer checks the acceptance criteria by id
- [ ] Template tests: the shape (the steps in order, `move` only with `move_to`), only `engineer` and `commit_specs` write, only `publish` publishes, every Jira write is after a gate, `ask_jira` shows what its gate showed, options validate (priced models, `max_passes` range)
- [ ] Engine run on the fake runtime + `FakeAtlassian`, asserting what each agent receives (spec writer gets the brief, the planner gets the approved and edited spec, the lead gets `tasks.md`, the reviewer gets the spec) and what Jira records (questions comment, final comment with four links, the move)

## 6. Webhook-to-PR integration test
- [ ] API + worker test: a `FakeAtlassian.signed_delivery` for a status move matches a rule for `sdd`, the run starts, the approvals go through `POST /runs/{id}/approvals`, and the fake GitHub opens the PR with the `specs/<KEY>-<slug>/` files. `FakeAtlassian.posted` has the comment with the spec, plan, tasks and PR links, and `moved` has the transition
- [ ] Rejecting `approve_spec` ends the run `completed` with no branch pushed and no final comment

## 7. Docs, real run, changelog
- [ ] `docs/` page for the template (trigger rule, options, what Jira receives, Spec Kit layout)
- [ ] Real run with Claude: a real Jira site and repo, issue moved to the trigger status; read every step in the console; approve the gates; check the issue's comment links and status. Fix and record any lesson in `specs/lessons.md`
- [ ] `CHANGELOG.md` under `[Unreleased]`; roadmap row 7.5 gets its `[Plan](2026-11-17-sdd-template/requirements.md)` link
