# Dry run for every write

Roadmap phase: 13.8
Branch: plan/13.8-dry-run-every-write

## Context

A gate before a code write shows the diff (1.7, 3.6), and the evidence, review and protected-path checks (13.3 to 13.6) back it up. The other writes a gate guards are approved without being shown. SDD's last gate (`approve_pr`) guards three outward writes at once: the pull request (`github.openPR`), a Jira comment and a Jira transition (`jira.comment`, `jira.transition`). The approver sees the diff, but not the comment text with its links, the status the issue will move to, or whether that move is still possible. A transition the issue's workflow no longer offers fails only after the pull request is open. A gate before a new repo (`approve_repo`) shows a title and prompt, not the repo it will create. 7.2 left this gap open on purpose (tech-stack decisions: "a plan mode for every write stays in 13.8"), and only `jira_write_not_shown` makes sure a comment's artifact is the gate's input.

13.8 gives each outward write tool a **plan mode**: the tool works out what it would do, without doing it. The engine asks for these plans before the gate pauses, and the gate shows them under "What approving does". Approving runs the same calls for real. Before any write, the engine checks that the plans still hold; if one does not, it writes nothing. It then compares each result with its plan, and the event log shows the two side by side.

It builds on:
- **7.2 Jira tools, 7.5 SDD, 7.6 follow-up push, 1.8 / 1.12 GitHub writes.** These four tools are the platform's outward writes today (`PUBLISH_TOOLS`, `CREATE_TOOLS`, `JIRA_WRITE_TOOLS`). The engine resolves their arguments before the call (`body_from`, `notes_from`, `issue_from`, `links_from`).
- **13.3 / 13.6 hidden gate steps.** `<gate>.evidence` and `<gate>.review` are steps of their own before a gate, checkpointed, so a gate that runs again does not repeat them. A `<gate>.plan` step follows the same pattern.
- **11.5 / 11.6 gate review surfaces.** The Inbox review, the approval dock's sheets and the gate's step show what approving does. Today that is "Approving lets the run go on" with the repo and branches.

What drives the design:
- **Principle 3 (humans approve irreversible actions).** A person approves what they were shown, and nothing else is written. If what the tool would do has changed by the time of approval, the write is refused, not done differently.
- **Principle 4 (tools live in the platform).** The plan comes from the tool's own code, the same code that resolves the site, the issue, the transition, the branch and the base for the real call. A plan built elsewhere would drift from what the tool does.
- **Principle 6 (transparency).** The plan and the result are events, side by side, kept in the append-only log and the audit log.
- **Principle 5.** Comment bodies, PR titles and bodies, and issue statuses come from agents, Jira or the repo. They are shown as text or sanitised Markdown, never as HTML.
- **Lessons 9 and 10.** Ask what the run does next for every outward write. A tool that talks to Jira or GitHub is checked once against the real service, not only against the fakes.

## Scope

### In scope

- **The plan contract** (`agentic_runtime.plans`, beside `agentic_runtime.findings`, so tools and engine share it without depending on each other). A `WritePlan` has:
  - `node_id`, `tool` and `action` (`open_pr`, `push_to_pr`, `create_repo`, `comment`, `transition`);
  - `summary`, one line the platform writes ("Move KAN-5 from In Progress to Done");
  - `target`, what the write acts on (kind, label, URL);
  - `fields`, the values a result is compared with;
  - `body`, the Markdown to show, if the write has any (a comment, a PR body);
  - `pending`, the parts the platform fills in only after approval (`links`, `review_notes`);
  - `expect`, the preconditions handed back at apply time;
  - `error`, a fixed code and text when the write would fail.
- **A plan mode on all four outward writes**, through engine-only arguments `plan: true` and `expect: {…}`. The tool servers accept them, a spec's `args` may not set them (validation `reference`), and the manifests do not list them.
  - `jira.comment`: the site and issue (project scoping checked), and the text exactly as it will be posted, footer included. A `links_from` list is a named placeholder ("the pull request `publish` opens, and 3 files"). If the same comment is already posted, the plan says so (`created: false`).
  - `jira.transition`: the issue's status now, the transition chosen and the status it leads to. If the issue already has that status, the plan says "no change". If the move is not offered, the plan carries the error `transition_unavailable` with the moves that are offered. `expect` holds the status now and the transition id.
  - `github.openPR`: the repo, the head branch (`agent/<run>/<node>`), the base, the commits to push (count and tip), the title, and the body as resolved (`notes_from` as a placeholder). If a pull request is already open from that branch, the plan says so. In a 7.6 follow-up the plan is to push N commits onto PR #n's branch as a fast-forward from `after_sha`, plus the one fixed comment. `expect` holds the tip.
  - `github.createRepo`: the organisation, the name, whether it is private, the `.gitignore` and the license, and whether the name is free. `expect` says the name is free, or that this run created the repo.
  - Plan mode only reads. A test shows that `FakeAtlassian.posted` and `moved` stay empty, and that nothing is pushed or created.
- **Which gate plans which writes.** A gate plans every outward write that comes after it in run order, up to the next gate that will certainly run before that write (validation's scope rule, `_runs_in`). So SDD's `approve_pr`, which sits in a router route inside the loop, plans `publish`, `jira_update` and `move`. A write may be planned by more than one gate. The plans of the last gate that ran before it are used. `wait_for` and breaker pauses plan nothing.
- **The `<gate>.plan` step.** A hidden step before each gate that plans writes. It comes after `<gate>.evidence` and `<gate>.review`, and it is skipped when they send the work back. It calls each guarded write in plan mode through the run's `ToolExecutor`, as the engine (never an agent). It resolves `body_from`, `notes_from` and `issue_from` as the tool node will, writes `writes_planned` (the gate and its plans) and keeps the plans in the checkpointed state (`RunState.plans`). It runs again on every pass of a loop. `gate_waiting` and `GET /runs/{id}/gate` carry `plans`.
- **Applying against the plan (refuse stale).**
  - **Check before the first write.** Before the first write of a gate's batch runs, the engine plans every write in the batch again and compares each new plan with the approved one: `fields`, `expect` and the body without its `pending` parts. If any of them differs, including a plan that would fail and now would not, or the other way round, the batch stops before anything is written. The step fails with `plan_stale: …`, naming what changed.
  - **At the call.** Each write gets its `expect`. The tool refuses with `plan_stale` if a precondition no longer holds: the issue's status, the transition is no longer offered, the branch tip, the repo name is taken. This covers the seconds between the batch check and the call.
  - **Adjustments the platform makes.** Gate edits move a writer's tip to the edit commit (`gate_decided.commits`), and the expected tip follows. Links and review notes are filled in from the platform's own results, never from model output, and the comparison derives them the same way.
  - Rerun from the gate (12.4) plans again and asks again.
- **The result check.** After each write, the engine compares the result with its plan, field by field for each tool:
  - comment: the issue and the text posted;
  - transition: the issue, the status before and the status after;
  - pull request: the repo, head, base, commit, title and body;
  - repo: the full name and whether it is private.
  It writes `write_checked`: `gate`, `plan`, `result`, `outcome` (`as_planned`, `differs` or `stale`) and `differences` (`{field, planned, actual}`). A difference is flagged: the step is marked and an audit entry is written. The write has already happened, so a difference does not stop the run.
- **Store, API and audit.**
  - `GET /runs/{id}/gate` gains `plans`.
  - The audit log gains `write.not_as_planned` and `write.plan_stale` (actor: system).
  - The OpenAPI spec and the web client are regenerated.
  - No migration: plans live in events and in the checkpoint.
- **UI.**
  - **"What approving does"**: one card per planned write in the Inbox review, the approval dock's details and review sheets, and the gate's step Output.
    - Each card has an icon for its kind and the summary line.
    - The target: the repo with `repoLabel` in mono; the issue key in mono, linked only when its address is https.
    - The details: the comment or PR body as sanitised Markdown, capped with "Show full"; a transition as "In Progress → Done" in text; a placeholder as a quiet line ("Links to the pull request are added after it opens").
    - A plan that would fail shows a `StatusBadge` "Would fail" and the error as text.
    - The cards replace "Approving lets the run go on" when the gate has plans. A gate with none keeps that line.
  - **The write step's Output**: a quiet line "As planned at approve_pr", or a `StatusBadge` "Not as planned" with each difference (field, planned, actual) as text. The step list reads the same. A `plan_stale` failure shows in the failed-run banner with its reason.
  - **Audit**: the formatter gains a line for each of the two new actions.
  - Loading, empty and error states come with the gate's own data. Every surface is checked at 375 and 1440 px, in light and dark.

### Out of scope

- Asking again on its own when a plan went stale (a new pause with a fresh plan). Today the step fails and "Rerun from <gate>" plans again. This can be added if stale plans turn out to be common.
- A "Check again" button that plans again while the gate waits. It needs a worker during the wait, which gates do not hold.
- Plans for writes inside the sandbox (`repo.write_file`, `repo.commit`, the engine's `repo.commitArtifacts`). The gate's diff is their plan already.
- Plan modes for tools that do not exist yet. 18.2's GitHub issue tools, 15.4's user tools that write, 14.5's run-record push and any later cloud write must ship with one. tech-stack records the rule; the phases that add them build it.
- Rehearsal runs against twins of the services (17.6), and the earned-autonomy rule "no plan mode, no autonomous gate" (parked in `ideas.md`).
- Turning Approve off when a plan would fail. Approve stays on. The batch check then stops the run before anything is written, and the reason is shown.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Which writes get a plan mode | All four outward writes: `github.openPR` (with the follow-up push), `github.createRepo`, `jira.comment`, `jira.transition` | Chosen by the user. The phase is "every write". Leaving the two GitHub tools out would leave the pull request and the new repo shown only partly. |
| What happens when the world changed | The write is refused (`plan_stale`). A check of the whole batch before the first write, plus `expect` at each call. Differences found after a write are flagged | Chosen by the user. Principle 3: nothing unapproved is written. The batch check catches what changed during the hours a gate waits, before a pull request opens with a Jira move that would then fail. `expect` covers the seconds between. |
| Where a plan comes from | The tool's own plan mode (`plan: true`), called by a hidden `<gate>.plan` step through the run's executor | Chosen by the user. The same code resolves site, issue, transition and branch for both calls (principle 4). Only a tool can check a transition or a repo name before approval. A hidden step is the 13.3 pattern, so a gate that runs again repeats nothing. |
| `plan` and `expect` as arguments | Engine-only arguments, refused in a spec's `args` and absent from the manifests | The plan is the same call with a flag, which is the idea's "same call for real". Refusing them in specs keeps a workflow from approving a dry run that never writes, or from forging a precondition. |
| Which gate shows a write | Every gate after which the write can run before another gate certainly runs. At apply time, the plans of the last gate that ran are used | In SDD with checks, the validator's gate for `publish` is `checks`, which passes by itself, while a person approves at `approve_pr` in a router route. Tying plans to the validator's gate would show them where nobody looks. |
| Parts known only after approval | Named placeholders (`pending`): the comment's links, the PR's review notes. Gate edits move the expected tip | These parts come from the platform's own results (the PR URL, the comments not dismissed, the edit commit), never from a model. The comparison derives them the same way, so they cannot hide a change. |
| Names | The UI says "What approving does". The events are `writes_planned` and `write_checked` | "Plan" already means an orchestrator's plan (`plan_made`) and SDD's `plan.md`. A third meaning would confuse the console. |
| Order of work | Plan contract and tool modes, then the engine's plan step and apply check, then API, events and audit, then UI, then a real run | Chosen by the user. Each group leaves the project working, and the UI builds on a stable `plans` payload. |
| Validation | Tool, engine, API and web tests, e2e with axe, and one real SDD run with Claude on a real Jira site and repo | Chosen by the user. Lessons 10: a tool that talks to Jira and GitHub is checked against the real service once. |

## Open questions

- The wording of each `summary` line and card label is settled when the UI is built, and recorded in tech-stack → UI design system.
- Whether a 7.6 follow-up's push can go stale in a way `--force-with-lease` does not already refuse. The plan checks it and tech-stack records the answer.
