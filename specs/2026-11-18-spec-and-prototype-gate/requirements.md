# Spec and prototype at one gate

Roadmap phase: 7.8
Branch: plan/7.8-spec-and-prototype-gate

## Context

Last phase of Milestone 7, and the first one of it not yet planned (the "Next up" line still says 7.3, but 7.3 to 7.7 are done; fix the line in this PR). Everything it builds on exists: the SDD template with its spec gate and Spec Kit files (7.5), the spec from a Markdown file (7.7), the loop primitive (1.9), editable gates on writer branches (3.6) and `on_reject: end` (6.7). 7.5 deliberately left two things for this phase: a gate shows the step before it, and an approver cannot send a spec back with comments (a gate only approves or rejects).

A vague spec makes every later step wrong, and text alone is hard to judge. The spec gate should show what the build will rest on: the product spec, the technical plan and, for UI work, a throwaway prototype to react to. Its acceptance-criterion ids are what 13.4 later checks as fail-to-pass.

Principles: **3** (the prototype branch is never pushed; the gate and every write stay), **5** (comments, the spec and the prototype are data; the platform, not a model, shows and routes them), **7** (existing primitives, the smallest engine addition: a third gate decision), **10** (contracts go into tech-stack in this PR). It changes what agents receive (new agents and instructions, comments as input), so lessons rule 1 applies: tests assert what each agent receives, and a real Claude run is read step by step in the console before the phase is done.

Source: the idea "Spec and prototype together" in `ideas.md` (promoted).

## Scope

### In scope

- **Spec Kit layout, extended.** The spec step writes two artifacts: `spec.md` (the product spec: problem, users, success measures, scope, out of scope, open questions as `[NEEDS CLARIFICATION: …]`, and acceptance criteria as `AC-001…`, each in the testable "When … the system shall …" form) and `plan.md` (the technical plan: design, files touched, risks, test plan). The `planner` and `tasker` after the gate keep working from the approved files; `tasks.md` is unchanged and still comes after the gate. Both files are still committed to `specs/<KEY>-<slug>/` (7.5).
- **A throwaway prototype for UI work only.** The spec writer states in a typed answer whether the work has a UI (`has_ui`). When it does, a `prototype` writer builds a UI mock or spike on its own sandbox branch (`agent/<run>/prototype`) and commits it. The branch is never pushed: `publish` refuses it, validation rejects a `github.openPR` or integration merge from it, and the implementation does not start from it.
- **One gate, three things.** `approve_spec` shows the spec, the plan and, when there is one, the prototype's diff, each with its own tab in the review. The approver can comment on any of the three.
- **A third gate decision: Request changes.** A gate gains `on_changes` beside `on_reject`. With it set, the review offers Approve, Request changes (comments, one per item) and Reject. Request changes ends the gate with `decision: "changes"` and the comments as its output; the engine hands them to the loop around the spec step. Without it, a gate behaves as today.
- **A revise loop.** The spec step (spec writer, prototype, gate) runs in a loop with `max_revisions` (new SDD option, 1 to 3, default 2). On a pass after a request for changes, the spec writer receives the last spec, the last plan and the comments as data (principle 5), and revises; the prototype writer revises its branch only when a comment concerns it. A gate past the last revision offers Approve and Reject only.
- **Inbox and approval dock** show Request changes and the comment form; the run console shows the comments on the step they came from.
- **Docs and specs:** the template section of `docs/`, tech-stack's "Build from a Jira issue template" and gate contract, `lessons.md` after the real run, roadmap and changelog.

### Out of scope

- Gates and writers in a **map or a parallel** stay refused (they inherit `_not_in_loop`'s check today and keep their own rule); only a loop's body is lifted. A loop in a loop, a publisher and a Jira write in a loop stay refused.
- Editing the spec text at the gate (a gate edits branch files, not artifacts; 7.5's finding). The approver comments and the agent revises.
- A prototype for non-UI work, a running preview served from the sandbox, or keeping the prototype after the run.
- Checking each acceptance criterion against tests: 13.4. This phase only gives the criteria ids and the testable form.
- Per-line comments on the diff (14.2 reads why beside a hunk; a comment here is on one of the three items).
- Changing the "Build from a spec file" template (7.7) beyond what it shares with SDD, and "Answer a Jira issue".

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Prototype | Only for UI work, decided by the spec writer's typed `has_ui` | User's choice. Avoids a spike on every backend run; a typed field the engine routes on, not text matching |
| How comments send the spec back | A gate's third decision, Request changes (`on_changes`), inside a loop | User's choice. Reuses the loop primitive; "reject" keeps one meaning (end the run) |
| Where the prototype lives | Its own writer branch, never published | Principle 3: a push is irreversible. Reuses the worktree-per-writer model (1.6) and its saved bundles (12.2) |
| Criteria form and ids | "When … the system shall …", `AC-001…` | The roadmap's wording; the ids are what 13.4 links to tests. `AC-` is the product spec's id for platform acceptance criteria, so the run's use is read as the spec's own: confirm the prefix in the plan, the alternative is `REQ-` |
| Plan before the gate | `plan.md` written with the spec; `planner` after the gate refines it from the approved spec and the comments only if it changed | The approver judges the technical plan too; a second plan step must not contradict an approved one |
| Revision cap | `max_revisions` option, default 2 | A loop with no cap is a spend risk (principle 2); consistent with `max_passes` |
| Gates and writers in a loop | Lift the loop rule (`not_allowed_in_loop`) for a gate and for writers: a gate's decision, its `gate_waiting` and its expiry are keyed by `(run, node, iteration)`, and a writer in a loop commits onto its one branch each pass | User's choice, after the plan's loop turned out to be refused: a loop's body holds no gate or writer today (6.9; 7.6 made each review round its own run). Keeps one run, one cost line and one console story for the revisions |
| Feedback path | Gate output carries the comments; the loop's next pass reads them through `results.approve_spec` as data | Same mechanism as 6.9's reviewer-to-lead feedback, no new input channel |

## Open questions

- The prefix of acceptance-criterion ids (`AC-001` against `REQ-001`): to confirm against the product spec when the spec writer's instructions are written (plan group 3).
- Whether `has_ui` alone is enough or the spec writer also needs to name the screens to mock: settled by the real run, recorded in lessons.
