# A run that asks waits for the answer

Roadmap phase: 7.9
Branch: plan/7.9-wait-for-answers

## Context

A bug in 7.5: `clarify` posts the spec's open questions with `ask_jira` and the run carries on to `tasker` and the build, on assumptions the team has not confirmed. `post_questions` only asks whether to post. The spec (tech-stack, "Open questions in SDD") described exactly that, so the spec is wrong too (lessons rule 9). Principle 3 (no irreversible step on a guess) and rule 4 (waiting is never active time) drive the fix. It reuses 7.8's gate-in-a-loop and 7.3's Jira webhook.

## Scope

### In scope
- Engine: a `wait_for` step in the waiting state, persisted and recovered like a gate, never active time.
- SDD template: the clarify cycle (questions, post gate, `ask_jira`, `wait_for`, `spec_writer` again, `approve_spec`), `max_clarifications` (default 2), a `build_on_assumptions` gate after the last round, a timeout (`answer_ttl_s`, default 7 days) that ends the run as "Waiting for answers expired". New gate prompt wording.
- Jira: `jira:comment_created` webhook; match a comment to the run waiting on the issue; drop the platform's own comments; ids only from the payload. Direct check through `get_issue` (the latest 20 comments), by a worker sweep and by "Check now".
- Console: "Waiting for answers on KAN-5" with Check now and a link to the issue, built from `StatusBadge` and `WaitingTime`.
- Specs, lessons entry, changelog; tests below; a real Claude run.

### Out of scope
- Answers from anywhere but Jira comments (Slack, e-mail); "build from a spec file" has no Jira and keeps answering at `approve_spec`.
- Reminders and @-mentions of the people asked (a later idea).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Waiting mechanism | `wait_for` = an interrupt like a gate, same `gate_waiting` event with a `wait_for` payload | Reuses checkpoint, recovery, expiry, Inbox, `waiting` status, active-time accounting |
| Who resumes | The API (`answer_arrived`), never a human decision | A person cannot approve a wait by accident |
| Resume routes | Webhook and a direct check (sweep and "Check now"), idempotent | Webhooks get lost; a poll alone is slow |
| Loop shape | One `spec_loop`: `spec_writer`, `planner`, `ui`, `approve_spec`, `clarify`; `until` stops on an approval with nothing to ask | A loop may not hold a loop (7.8), and the run must go back to `approve_spec` |
| Limit | `max_clarifications` 1 to 3, default 2, then `build_on_assumptions` | Bounded, and a person decides to build on guesses |
| Timeout | `answer_ttl_s` default 7 days; ends `cancelled`, reason "Waiting for answers expired" | Never builds silently |

## Open questions
- Does a CEL loop condition see `iteration` and the router result clearly enough to count clarification rounds apart from revisions? (`iteration` exists in `expr.py`; the first task confirms it, else the rounds are counted by the `wait_for` result.)
- How large is the engine change? Estimate from reading `gate.py`, `graph/run.py`, `graph/compile.py` and the store's approvals and expiry: about 12 files in the engine and store, because every place that matches `GateNode` or `GATE_WAITING` needs a decision. See plan.md.
