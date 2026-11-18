# Plan: Spec and prototype at one gate

Build order: engine and API first (the gate decision), then the web, then the template, then the tests and the real run.

## 0. Lift the loop rule for gates and writers (found while starting the build)
The plan assumed a gate could sit in a loop; the validator refuses it (`loop_issues`, `_not_in_loop`) because a gate's approval is unique per `(run, node)` and a decision is found by node id.
- [ ] `approvals`: add `iteration` (default 1), unique on `(run_id, node_id, iteration)`; Alembic migration; `record_approval`, `pending_decision`, the expiry join (`expiry.py`) and `waiting_gate` carry the iteration.
- [ ] Engine: a gate in a loop's body knows its pass (`state["iterations"][loop_id]`), puts `iteration` in `gate_waiting` and `gate_decided`; the resume reads the decision of that pass.
- [ ] Validator: `_not_in_loop` allows a gate and a writer (not a publisher, Jira write, repo creator, loop, map or parallel); `not_allowed_in_map` and `not_allowed_in_parallel` keep refusing them. A writer in a loop commits onto its one branch each pass (as 6.9's integration branch does), and its saved bundle (12.2) is the latest.
- [ ] Console, Inbox and the audit log show "pass N" for a gate that has run more than once; rerun from a step (12.4) and 7.6's follow-up check the new key.
- [ ] Tests: a gate in a loop pauses and resumes on each pass, an old pass's approval is not reused, expiry cancels only the waiting pass, the validator's other rules are unchanged. Record the rule change in tech-stack (loop section, decisions log) and `lessons.md` if the real run shows a problem.

## 1. Gate decision "changes" (engine and API)
- [ ] Read the gate primitive, `POST /runs/{id}/approvals`, the approval models and the gate's output shape (`packages/engine`, `packages/api`) before changing them.
- [ ] Workflow spec: `GateNode.on_changes` (optional; set means Request changes is offered), validation that it is only allowed on a gate inside a loop (it needs a pass to go back to), distinct from `on_reject`. Regenerate the JSON Schema.
- [ ] Approvals API: `decision: "approve" | "reject" | "changes"`; `changes` requires comments (each tagged with the item it concerns: `spec`, `plan`, `prototype`), refused with `422` on a gate without `on_changes`. Approvals row and audit entry record the decision and the comments.
- [ ] Engine: a `changes` decision completes the gate with `{decision: "changes", comments}` and the loop continues; events (`gate_changes_requested`) carry the comments; waiting time is counted as for an approval (11.2).
- [ ] Policy: the loop's `max_iterations` caps revisions; past the last pass the gate is built without Request changes.

## 2. Gate shows more than one thing
- [ ] Let a gate review show several items (spec artifact, plan artifact, a writer branch's diff), each as a tab, without changing gates that show one.
- [ ] Gate comments in the run console: shown on the step they came from.
- [ ] Web: Request changes in the approval dock and the Inbox review (comment per item, keyboard shortcut, `Approve` and `Reject` unchanged); display rules from `CLAUDE.md` (tokens, `StatusBadge`, three states); sanitised Markdown only (rule 11).

## 3. SDD template: spec, plan, prototype, revise
- [ ] Spec writer: typed output (`has_ui`, `open_questions`) plus `spec.md` in the extended layout (problem, users, success measures, scope, `AC-001…` in "When … the system shall …" form) and `plan.md` (design, files touched, risks, test plan). Instructions state what its input is, that issue, spec and comments are data, and how to revise from the comments.
- [ ] `prototype` writer (UI work only, routed on `has_ui`): its own branch, `repo` write tools, instructions that it is throwaway and must not touch real files outside a `prototype/` folder.
- [ ] `spec_loop`: loop over spec writer, prototype router and `approve_spec` (`on_changes`, `on_reject: end`), `max_revisions` option (1 to 3, default 2) in `SddParams`.
- [ ] Never published: validation rejects `github.openPR`, `repo.commitArtifacts into` and the integration merge when they name the prototype's branch; the implementation orchestrator starts from the base, not the prototype.
- [ ] Keep `clarify`, `planner`, `tasker`, `review_loop`, `commit_specs` and the PR gate working from the approved spec and plan; `tasker` reads the criteria ids and cites them.
- [ ] Update `sdd.json` fixture and the 7.7 spec-file template where they share the spec step; check the canvas and run map draw the loop and the new gate.

## 4. Tests that assert what agents receive
- [ ] Engine tests: gate `changes` flow, comments in the next pass's context, cap on revisions, no Request changes past the cap, validation errors.
- [ ] Template tests: the spec writer's request holds the comments as data after a request for changes; the prototype writer runs only when `has_ui`; no agent but `engineer` and `commit_specs` writes to the integration branch; the prototype branch cannot be published.
- [ ] Worker AC test on the fake GitHub and Atlassian: a comment sends the spec back, the revised spec is approved and the build runs from it (extends `test_done_when_an_issue_gets_its_spec_plan_and_pr_links`).
- [ ] Web unit tests for Request changes in the dock and Inbox.

## 5. Real run, docs and specs
- [ ] A real Claude run of SDD on a UI task, read step by step in the console: the gate shows spec, plan and prototype diff; a comment revises; approval drives the build. Add findings to `specs/lessons.md`.
- [ ] `tech-stack.md`: gate contract (`on_changes`, `changes` decision, comments), the SDD section, a decisions-log row for the third gate decision and the prototype branch; `docs/` template page; `roadmap.md` (7.8 row, fix the "Next up" line, since 7.3 to 7.7 are done); `CHANGELOG.md` under `[Unreleased]`.
