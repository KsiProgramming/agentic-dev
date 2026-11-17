# SDD template (spec, plan, tasks, implement, review, PR, Jira update)

Roadmap phase: 7.5
Branch: plan/7.5-sdd-template

## Context

Fifth phase of Milestone 7, the one the roadmap's "Next up" line names. Everything it needs exists: a Jira connection (7.1), the `jira` tools with gated writes (7.2), a webhook trigger that starts a run with the issue key as its input and `runs.jira_issue` set (7.3), and the issue brief with mapped acceptance criteria in every agent's run context (7.4). The engine already has what the build part needs: an orchestrator in a review loop on one integration branch (6.9), editable gates (4.x), `on_reject: end` (6.7), and `github.openPR` with `body_from` (6.7). "Plan, build and review" (6.8) is the closest template.

This phase is AC-5 (product spec US-5, §6.3): *moving a Jira issue to the trigger status starts SDD; the issue receives spec, plan and PR links.* It is the third of v1's three day-one outcomes (mission, "What we deliver").

Stages follow GitHub Spec Kit's spec → plan → tasks → implement, so the files a run leaves in the repo are ones Spec Kit reads (product spec §6.3).

It changes what agents receive (new agents, new instructions, and the issue brief for runs started by hand), so lessons rule 1 applies: tests assert what each agent receives, and the phase is done only after a real run with Claude has been read step by step in the console.

Principles that drive it: **3** (the PR, every Jira comment and the transition are behind gates), **5** (the issue, the spec and the code are data; the platform, not a model, writes the links posted to Jira), **7** (one template on existing primitives, with the smallest engine additions it needs), **10** (contracts go into tech-stack in this PR).

Unblocks 7.6 (PR review comments feed the loop), 7.7 (SDD from a Markdown file) and 7.8 (spec and prototype at one gate, in this phase's Spec Kit layout).

## Scope

### In scope

- **Template `sdd`** ("Build from a Jira issue", `agentic_engine.templates.sdd`), requires Claude, GitHub and Jira, with a required `input` declared as a Jira issue ("Which Jira issue?", example `PROJ-12`). The flow:
  1. `spec_writer`: reads the issue (brief in the run context, `jira.getIssue`, `jira.search` for linked issues) and the code (repo read tools); writes `spec.md` in Spec Kit's spec layout (user scenarios, functional requirements `FR-001…`, success criteria, the issue's acceptance criteria kept, and each open question as `[NEEDS CLARIFICATION: …]`).
  2. `approve_spec`: a gate on the spec writer's answer, `spec.md` (approve or reject; see "Settled" for edits), `on_reject: end`. Rejecting it completes the run without building, for instance while the team answers the questions in Jira. Moving the issue again starts a fresh run.
  3. `clarify`: a rule router with `otherwise: "skip"`. When the approved spec has open questions, route `ask`: `questions` (no tools, reads `spec.md`) writes `questions.md`, the gate `post_questions` shows it (rejecting cancels the run), and `ask_jira` (`jira.comment`, `body_from: questions.md`) posts it. Otherwise nothing runs. It comes after the spec gate because a gate shows the step before it: placed before, the spec gate would show the posted comment instead of the spec.
  4. `planner` writes `plan.md` (approach, files touched, risks, test plan); `tasker` writes `tasks.md` in Spec Kit's tasks layout (`T001`, `[P]` for parallel, the files each task touches). Both read the code and `spec.md`.
  5. `review_loop`: a loop until `results.reviewer.data.verdict == "ok"` (at most `max_passes`) over `implement` (an orchestrator: its lead has the repo read tools and plans worker tasks from `tasks.md`, keeping dependent tasks in one worker task; the worker `engineer` writes and commits), `synthesizer` (writes `pr-description.md`) and `reviewer` (checks the merged work against `spec.md`'s requirements and acceptance criteria; typed `verdict` and `feedback`).
  6. `commit_specs`: a deterministic tool step that commits `spec.md`, `plan.md` and `tasks.md` to `specs/<KEY>-<slug>/` on `implement`'s integration branch, so they are in the PR and shown in the gate's diff.
  7. `approve_pr`: a gate on the integration branch's diff. Its prompt says what Jira will receive.
  8. `publish`: `github.openPR` from `implement`, `body_from: pr-description.md`.
  9. `jira_update`: `jira.comment` on the issue with a fixed body and **links the platform makes**: the spec, plan and tasks files on the PR's branch, and the PR's URL taken from `publish`'s result.
  10. `move`: `jira.transition` to the `move_to` option, present only when that option is set.
- **Options (`SddParams`):** `max_passes` (1 to 3, default 2), `move_to` (a status name, unset means no transition), `spec_model`, `planner_model` (the planner and the tasker), `engineer_model` (the lead and the engineers) and `reviewer_model` (the synthesizer and the reviewer). Unset uses the workspace default; when set, it must be a priced model.
- **Engine and tools: platform-made links on `jira.comment`.** `links_from: {pr: <publisher>, files: <commit step>}` (as settled below). The engine resolves them to URLs after the steps they name have run and appends them to the body as a list; the tool never sees them. Validation: each source names a step before the comment (`reference`), and the gate before the publish also covers the comment.
- **Engine and tools: commit artifacts onto a writer's branch.** A tool node (`repo.commitArtifacts {into, dir}`, committing the artifacts it `reads`) writes them to `dir` on the branch of the writer `into` (an orchestrator's integration branch) and commits them as the agent identity. `dir` may use `{issue}`, the run's issue as `<KEY>-<slug>`. A publish of `into` needs a gate after it, so the gate shows the files.
- **Issue brief for runs started by hand.** A workflow whose `input` says it is a Jira issue (`input.kind: "jira_issue"`) gets `runs.jira_issue` from `POST /runs` and from rerun when the input is an issue key. The project must be picked on the single enabled site (`422` `site_required`, `project_not_allowed` otherwise). From then on it works like a triggered run: the worker reads the brief once before the first step. A run whose input is not an issue key is refused (`422` `issue_invalid`).
- **Console:** no new screen. The template's gates and steps use what exists. The start sheet labels the input as a Jira issue.
- **Docs:** the template in `docs/` (what it does, the trigger rule to create, what Jira receives), and tech-stack's "SDD template" section.

### Out of scope

- Scheduling tasks by dependency in the engine (`depends_on` in the orchestrator's plan). The lead keeps dependent tasks in one worker task. To be added when a real run shows it is needed.
- "Each task loops on tests" (product spec §6.3, step 5): build and test evidence is 13.3.
- PR review comments feeding the loop: 7.6. A spec from a Markdown file: 7.7. A plan and a prototype at the spec gate, and comments that send the spec back: 7.8.
- Retiring "Answer a Jira issue": it stays (decision below).
- A plan gate between `tasker` and `implement` (the roadmap row has none; 7.8 brings the plan to the spec gate).
- Sub-tasks or fields written back to Jira.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Spec Kit files | `spec.md`, `plan.md` and `tasks.md` committed to `specs/<KEY>-<slug>/` in the PR, also kept as run artifacts | The Jira comment links real files, and Spec Kit reads them later (user's choice; product spec §6.3) |
| How Jira gets the PR link | `jira.comment` gains `links` resolved by the engine; one PR gate covers the PR, the comment and the transition | The link exists only after `openPR`, and a second approval would add no information. The links are platform-made, never model text (principle 5) (user's choice) |
| Open questions | Spec Kit's `[NEEDS CLARIFICATION: …]` markers. After the spec is approved, a rule router posts them through their own gate | Product spec §6.3, step 3 (user's choice). Posting is irreversible, so it has a gate (principle 3) |
| Spec gate rejected | `on_reject: end`: the run completes without building | Not building while questions are open is a good outcome, not a cancellation (as in 6.7) |
| Manual starts | `input.kind: "jira_issue"` makes `POST /runs` set `jira_issue`, so a manual run gets the same brief | Settles 7.4's open item (user's choice). SDD behaves the same whether a trigger or a person starts it |
| Plan and tasks | Two agents, `planner` → `plan.md` and `tasker` → `tasks.md` | One artifact per step (4.3), and Spec Kit's `/plan` and `/tasks` stages |
| Task dependencies | The lead groups dependent tasks into one worker task; no engine scheduling | Keeps the phase on existing primitives (principle 7). The orchestrator merges in plan order already (6.3) |
| "Answer a Jira issue" | Kept | It is a cheap, read-mostly template that SDD does not replace (user did not choose to retire it) |
| Build order | Engine and tools first (links, commit artifacts, manual brief), then the template, then tests and the real run | User's choice. The template needs the engine pieces to validate |

## Settled while starting the build

The four open questions of the plan, and one thing the code showed, were settled in plan group 1:

| Question | Settled | Why |
|---|---|---|
| A router with nothing to run | `RouterNode.otherwise: "fail" \| "skip"` (default `"fail"`, today's behaviour). With `"skip"` and no default, a rule router that matches no route completes with its input as its output and runs nothing (`route_chosen` `{route: null, reason: "no route matched"}`; `node_completed` `{route: null, skipped: true}`). It is allowed in rule mode only | Explicit, so no existing workflow changes. A no-op tool node would show a fake step in the console |
| How `clarify` tests for markers | `when: results.spec_writer.text.contains("[NEEDS CLARIFICATION")` | `results` already carries each node's `text` (loop and router CEL). It needs no extra agent turn when there are no questions |
| Links to files | The PR's "Files changed" anchors: `<pr url>/files#diff-<sha256 of path>` | They still work once the branch is deleted after merge |
| Slug | From the brief's summary: lowercase ASCII words joined by `-`, cut at 40 characters on a word. With no brief, or an empty slug, it is `specs/<KEY>/` | Deterministic, and Spec Kit reads any `specs/*/spec.md` |
| **Editing the spec at its gate** (found in the code) | Not in 7.5: `approve_spec` approves or rejects. A gate edits files on writer branches (4.x), not run artifacts, and `spec.md` is an artifact until `commit_specs`. The approver who wants changes rejects (the run ends) and comments in Jira, or waits for 7.8, which sends a spec back with comments | Making artifacts editable at gates is a contract of its own (API, engine, web). 7.8 already owns revising the spec at its gate |
| How `commit_specs` writes | `repo.commitArtifacts` is run by the engine, not an MCP server. It reads the artifacts and commits them through `GateReview.apply` (the gate's edit commit, idempotent), with its own message `Add Spec Kit files for <KEY>` | It reuses the one tested path that commits onto an integration branch. The engine still never runs git |
| How `links_from` gets the PR | `jira.comment` takes `links_from: {pr: <publisher id>, files: <commit step id>}`. The engine reads the publisher's result (`data.url`) and the commit step's paths from the run's results | Platform-made, deterministic, and never model text |

## Open questions

- None.
