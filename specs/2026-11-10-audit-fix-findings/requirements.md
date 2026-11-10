# Audit "fix selected findings" step with orchestrator

Roadmap phase: 6.7
Branch: plan/6.7-audit-fix-findings

## Context

The "Audit codebase" template (4.6) checks a repo and writes `findings.json` and `report.md`. It is read-only by construction: no writer, no gate, no pull request. A team that reads the report then fixes the findings by hand. 6.7 closes that loop. The person picks the findings worth fixing, and the run fixes them and opens a pull request.

Everything it builds on is done:
- 4.5 merged findings with stable `fingerprint`s, which identify a finding across scanners;
- 4.3 run artifacts, so `findings.json` can be read by name;
- 6.1–6.3 the orchestrator: a hub plans tasks, writers fix them on task branches, replan on failure, and one integration branch merged in plan order is what a gate shows and `openPR` publishes;
- 6.4 the console shows the fix tasks live with progress and cost;
- 1.7 and 3.6 gates with review and edits; 11.5 the Inbox.

What is missing is a way to **choose**. A gate can only approve or reject. 6.7 adds a **selection gate**: a gate that shows a JSON artifact's items as a checklist, and whose approval carries the chosen items. It is a generic part of the gate primitive, not something only the audit has, so 13.6 (findings to the writer or to the gate) and 18.2 (approve a batch of issues) can reuse it.

It unblocks 6.8 (AC-2 needs a canvas flow with an orchestrator and a gate) and is the first template where an orchestrator writes code that a person asked for.

Principles that drive it:
- **Humans approve irreversible actions (3):** two gates. The person selects the findings, then approves the diff before the push and the PR.
- **Repo content is data (5):** findings, task instructions and the fixers' summaries are model or repo output. They reach agents as input, never as instructions, and the web shows them as text.
- **Open, but safe by construction (2):** the selection is checked by the API and the engine against the items the gate showed, and the orchestrator's limits and replan still apply.
- **Small, verifiable steps (7):** with `fix` off, the template builds exactly the 4.6 spec it builds today.

Tech-stack choices it follows: gate review and approvals (Gate review API contract), run artifacts, the findings model in `agentic_runtime.findings`, the orchestrator contract (writers, integration branch, `openPR` from the orchestrator), CEL for conditions, manifests driving the side panel, and the UI design system (`SeverityBadge`, `TruncatedPath`, the three states). It follows the rules in `lessons.md`: the hub gets read tools (rule 4), every agent is told what its input is and what its tools read, and the phase is done only after a real Claude run has been read step by step (rule 1).

## Scope

### In scope

- **Selection gate (engine).** A `gate` takes an optional `select`:
  - `artifact`: a `.json` run artifact written before the gate;
  - `items`: the name of a top-level array field in it (`findings`);
  - `key`: the field that identifies each item (`fingerprint`);
  - `preselect`: an optional CEL condition over `item`, for the items checked by default;
  - `min`: the fewest items an approval may select (default 1).
  - When it waits, `gate_waiting` and `GET /runs/{id}/gate` carry `select`: the artifact name and version, `items`, `key`, the preselected keys and the item count. The web reads the items from the artifact.
  - On approve, the selection is checked against the items of that artifact version. The gate's output, and its `writes` artifact if set, is the same document with the array filtered to the selected items, in their original order. For a findings report, `counts` and `truncated` are recomputed, so the report stays valid. A select gate does not pass its input through unchanged, as other gates do.
  - Validation: `artifact_unknown` when no node always writes the artifact before the gate, and a new `invalid_gate` for a non-JSON artifact, an empty `items` or `key`, or `min` < 0. `preselect` is checked as any CEL expression (`invalid_expression`).
- **Ending at a gate.** A `gate` takes `on_reject: "cancel" | "end"` (default `cancel`, as today). With `end`, a rejection logs `gate_decided`, skips every step after the gate and completes the run. This is how a person says "no fixes": the audit still reads as succeeded. Only a step of the root sequence may set `end` (`invalid_gate` otherwise).
- **Approvals (API).** `POST /runs/{id}/approvals` takes `selection: [key, …]` (at most 1,000).
  - It is required to approve a select gate, and refused (`422`) on any other gate or with a reject.
  - Codes: `selection_required`, `selection_not_allowed`, `unknown_selection` (a key the gate did not show), `duplicate_selection`, `selection_too_small` (fewer than `min`).
  - The selection is stored with the approval. `gate_decided` adds `selection`. The `gate.approved` audit row adds `selected` (the count, never the items).
- **`github.openPR` body from an artifact.** `openPR` takes an optional `body_from`, the name of a `.md` run artifact. Its text, capped at 60,000 characters, goes under the static `body`. Validation: `artifact_unknown` as for a read.
- **Audit template: `fix` option.** `AuditParams` gains `fix` (default `false`) and `fixer_model` (a priced model, unset = the workspace default). With `fix` on, after `report_path`:
  1. `select_fixes`: a select gate on `findings.json` (`items: findings`, `key: fingerprint`, critical and high preselected, `on_reject: end`, `writes: selected-findings.json`). Its prompt says that rejecting ends the audit with no change to the repo.
  2. `fix`: an orchestrator. Its input is the selected findings report.
     - The hub (role "Lead engineer planning fixes") has the repo read tools. It groups findings that touch the same file into one task, so two tasks never edit the same file, and names each task's findings by fingerprint and `path:line`. It never plans a finding that is not in its input. `max_workers` 6, `max_concurrency` 3, `replan: {on: failure, max_rounds: 1}`.
     - The worker is one agent, `fixer`, with `repo.list_files`, `repo.read_file`, `repo.search`, `repo.write_file` and `repo.commit`. Its instructions say that its input is its task plus the selected findings, that its tools read and write its own task branch, to fix only its task's findings, and to commit with the fingerprints in the message. Its answer is a short Markdown summary: each finding fixed, or not fixed and why.
     - `writes: fixes.md`.
  3. `approve_pr`: a gate. It shows the integration branch's diff, which can be edited (3.6), and `fixes.md` among the run artifacts.
  4. `publish`: `github.openPR` from `fix`, with a static title and body (the run, the audit, "review as you would any change") and `body_from: fixes.md`.
  - With `fix` off, the spec is the one 4.6 builds, unchanged (a test compares them). The template's description says whether it writes.
- **Web.**
  - **Checklist.** A select gate's review shows the items as a checklist, in the Inbox review and in the dock's "Review details" sheet.
    - A findings report is shown as the Findings view is (`SeverityBadge`, `path:line` as `TruncatedPath`, the rule, the message as text), with a checkbox per row: a table from `md`, cards below. Any other item shows its key in mono and a one-line summary.
    - "Select all", "Clear", and "N of M selected". The preselected items are checked when it opens.
    - Approve reads "Approve with N selected". It is disabled under `min`, with the reason.
  - **Keys and buttons.** On a select gate, `A` and the dock's Approve open the review, so nothing is approved without the list being seen. With `on_reject: end`, Reject reads "End run here", and its dialog says the run completes without the steps after the gate.
  - **Step output.** The decided step's Output reads "Selected 3 of 12" and lists the selected items. Its step-list line reads the same.
  - **Side panel.** It edits `select` and `on_reject` from the gate's manifest, with no hand-written form.
  - Loading, empty ("The artifact has no items.") and error states for the checklist.
- **Fixtures.** `schemas/fixtures/audit-fix-run.json` is recorded from an engine test (as in 6.4), so the web folds a real event sequence. `node-types.json` is regenerated for the new gate parameters.
- **Specs and docs.**
  - tech-stack: Gate review (select, `on_reject`, the approval's `selection`), Audit codebase template (`fix`), `openPR`'s `body_from`, the validation codes, the Inbox, Run console and Approval dock rules, the audit log table, and decisions-log rows.
  - roadmap: a `[Plan]` link on 6.7.
  - `lessons.md`: an entry if the real run finds a gap.
  - `CHANGELOG.md`.

### Out of scope

- One PR per finding or per task. That needs a publisher inside an orchestrator's worker, which 6.1 forbids. One PR from the integration branch is what 6.3 built.
- Running the build or the tests on the fixes, and sending a failing fix back. Those are the evidence pack and verification gates (13.3, 13.4).
- A reviewer loop after the fixers (6.9's pattern). It can be drawn on the canvas, but the template keeps one pass.
- Fixing the findings of an earlier audit run from its console ("Fix selected" on a finished run). It would need a run started from another run's artifacts. For now a new audit run with `fix` on is the way.
- Filtering the checklist by severity, category or path. The list is at most 1,000 items, and select all, clear and preselect cover the first use.
- Protecting tests or config from the fixers (13.5).
- A selection gate inside a loop, a map or a parallel. Gates are not allowed there today, and this phase does not change that.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How findings are selected | A selection gate in the audit run, after the report | Chosen in the interview. The person decides after seeing the findings, inside one run, with a gate as principle 3 asks. |
| Selection: audit-only or generic | A generic `select` on the gate primitive (artifact, items, key, preselect, min) | 13.6 and 18.2 need the same "approve some of these" decision. A field on `gate` is reusable from the canvas with no new node kind. |
| What a select gate passes on | The artifact with its array filtered to the selection (a findings report's counts recomputed), also stored by `writes` | The hub's input is exactly what was chosen, as data. The artifact keeps the choice visible after the run. |
| How many PRs | One PR from the orchestrator's integration branch | Chosen in the interview. It is what 6.3 built, and it needs no publisher inside a worker. |
| How a person declines all fixes | `on_reject: end` on the select gate completes the run, skipping later steps | Rejecting cancels a run today, which would mark a good audit as cancelled. An empty approval would need a router with a no-op default. `end` is the smallest honest change. It is limited to root-sequence steps, where skipping to the end is well defined. |
| Grouping fixes into tasks | The hub groups findings by file, one task per group, with replan on failure (1 round) | Two tasks that edit the same file would conflict at integration (6.3). Replan (6.2) keeps one failed fix from losing the others. |
| What the PR says | `openPR` takes `body_from: fixes.md`, the fixers' summaries joined by the orchestrator | Tool args are static. The PR must say which findings it fixes and which it could not. The artifact is shown at the PR gate before it is pushed. |
| `A` on a select gate | It opens the review, it does not approve | Approving the preselection without seeing it would make the choice blind. |
| Order of work | Contract, then engine and template with fixtures, then API, then web, then a real run, in one PR | Chosen in the interview, as in 6.5 and 6.6. |

## Open questions

- None that block planning. To settle while building:
  - ~~If `on_reject: end` is awkward in the compiler, fall back to a router.~~ Settled: it was not. A rejected gate completes with `ends_run`, and the step's continue edge goes to the graph's end.
  - The `preselect` default for the template (critical and high) may change after the real run, if it preselects too much.

## Changed while building

- `on_reject` is optional, and unset means `cancel`. With a `"cancel"` default, the gate manifest's `default` carried it, so every gate added from the palette would have written it into the spec.
- The checklist is one list of rows at every width, not a table from `md` with cards below. Each row is a checkbox and its label. The rule is plain mono text, not a link, because a link inside the label would toggle the row.
- The decided gate's Output does not list the chosen items itself. With `writes`, they are its "Artifacts written" card (`selected-findings.json`), which opens in the Findings view.
- A fixer's `input` field is the orchestrator's input as text, a JSON string inside the worker's JSON (the 6.1 contract), not a parsed object. The fixer's instructions say what it holds. The real run should confirm the fixer reads it correctly.
