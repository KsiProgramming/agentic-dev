# Independent review

Roadmap phase: 13.6
Branch: plan/13.6-independent-review

## Context

13.3 to 13.5 made the platform check a writer's work before a person sees it (build, tests, analyzers, coverage, fail-to-pass) and protect what judges it. Judging the code itself is still left to one `reviewer` agent per template. That agent gets the previous step's answer as its input (the synthesizer's description of the work), reads the repo, and answers a `verdict`. It shares the writer's framing, usually its model, and nothing keeps it apart from the writer. The ideas entry calls this "monoculture". In 13.6 the platform runs reviewers that start fresh. Each looks through one lens, and the engine enforces that independence. What they find is sent back to the writer or shown to the approver on the lines it names.

It builds on:
- **4.1 `parallel`, 4.5 `dedupe`, 4.6 agent findings (`scanner: agent`)**: lenses in parallel, merged into one findings report.
- **6.6 composites and 6.5 subflows**: the review is reusable as a published workflow.
- **13.1 `repo.diff` and reads by `node`**: a reviewer reads the writer's committed work through git refs, never its worktree.
- **13.3 and 13.4 send-back**: the same path (`decision: "changes"`, `source`), rounds that never use the loop's last pass (lessons 13), and the SDD and plan-build-review `checks` layout.
- **8.3 provider selection**: a lens can run on another provider than the writer.

It covers what earlier phases left to it: in-code suppressions and analyzer settings inside a `.csproj` (13.5), and weak tests that prove a criterion (13.4).

What drives the design:
- **Principle 2 (safe by construction).** Independence is enforced by the engine on the node, not asked for in instructions or wired by the flow's author.
- **Principle 1 (one spec, many views).** Lenses are ordinary nodes, so the canvas, the run map and the console show them with no new view.
- **Principle 3.** Review findings never approve anything. They send work back or inform the person at the gate.
- **Principle 5.** Findings are model output: data for the writer, plain text at the gate. In the PR body, `@` mentions are neutralised.
- **Lessons 1, 8 and 13.** Write down and test what each lens receives. A lens still knows the request. Two send-back mechanisms on one gate count rounds together.

## Scope

### In scope

- **Review agents.** `review: {of?, spec_from?}` on `AgentNode`. On such a node the engine enforces:
  - **Fresh input.** Its input is built by the engine, never the previous step's output: the spec (`spec_from`, a Markdown artifact, optional), the reviewed writer's change (13.1's `repo.diff` header and diff, cut at a cap with a note to call `repo.diff {path}`), and the evidence pack of that writer from this pass when a gate collected one. The run's request still reaches it through `RunContext` (lessons 8).
  - **Read-only tools.** Only `repo.list_files`, `repo.read_file`, `repo.search`, `repo.list_modules` and `repo.diff`. No `artifacts.*`, so a lens never reads the writers' or synthesizer's narrative. No `reads`. No `input_schema` or `output_schema` of its own: the engine sets the findings schema (`scanner: agent`, its lens's category).
  - **The reviewed code.** Reads without `node` go to the reviewed writer's committed work (13.1's refs), never its worktree.
  - **`of`.** A writer, or an orchestrator whose body writes, that completes before the node. Unset means the latest such writer in run order, so a stored review composite works in any caller.
  - `node_started` carries `review: {of, spec, spec_version, diff: {files, added, removed}, evidence}`.
- **Six lens presets** in `agentic_engine.review.LENSES`, each with an id, title, category and instructions:
  - **correctness**, which also checks in-code suppressions (`# noqa`, `#pragma warning disable`, `biome-ignore`) and analyzer settings in `.csproj` files (13.5's gap);
  - **security**;
  - **performance**;
  - **tests**, which flags weak or tautological tests and tests that do not prove their criterion (13.4's gap);
  - **API compatibility**;
  - **accessibility**.

  The findings schema gains the categories `correctness`, `performance`, `compatibility` and `accessibility`, additively (v1).
- **A `review` builder** (`review_flow(of?, lenses, spec_from?, provider?, model?, writes)`): a `parallel` (join `settled`) of one review agent per lens, then a `dedupe` reduce that writes `review.json`. It is shipped as a composite fixture (`review-composite.json`) that a workspace stores and publishes (6.6), and it is used inline by the templates.
- **Gate `review`**: `review: {from, block_at, max_rounds, notes?}` on a gate in a loop's body.
  - `from` is a findings `.json` artifact written before the gate in the same body.
  - `block_at` is a severity (default `high`). Findings at or above it send the work back without a person, as `{decision: "changes", source: "review"}`. They go under `## Review` as data, capped, one line each: severity, `path:line`, lenses and message.
  - Rounds share one counter with the gate's `evidence` and never use the loop's last pass.
  - A lens that could not run (a failed branch of the `settled` join) is not the writer's fault: the gate pauses and names it.
  - Otherwise the gate pauses with every finding as a review comment. A blocking finding shown there (no rounds left) is marked "Blocking".
  - `gate_waiting` and `GET /runs/{id}/gate` carry `review`: the comments mapped to the writer whose diff holds their file, whether the line is in a changed hunk, the failed lenses and `rounds_left`.
  - The audit log records `gate.sent_back_by_review`, with the system as its actor.
- **Dismissing comments.** On approve, the approver may dismiss comments (`dismissed: [fingerprint]`). They are stored on the approval, and `gate_decided` carries them.
- **Review notes in the PR.** With `review.notes` (a Markdown artifact), approving writes the comments that were not dismissed. `github.openPR` takes `notes_from` and adds them under the body as `## Review notes`, capped, with `@` mentions neutralised.
- **A lens on another provider.** A lens takes `provider` and `model` like any agent. The templates get `review_provider` and `review_model`. Triggered runs still fall back to Claude (8.3).
- **Templates.** A `review` option, default off, in both SDD builders and in Plan, build and review. With it on:
  - the lenses (`review_lenses`, default correctness, security and performance) replace the single `reviewer` and its verdict;
  - `approve_pr` moves into the loop's body with `review` (and `evidence` when `checks` is on), and the loop ends on its approval;
  - `review_block_at` defaults to `high`;
  - the lead and engineers are told that a later pass's input may be review findings, as data;
  - with it off, every flow is unchanged.
- **Web:**
  - the gate's review comments appear in the diff on the lines they name (Monaco view zones on the changed side) and as a list beside the files (`ReviewComments`). The list is the keyboard and screen-reader path; selecting a row opens the file at its line. Findings on files the change did not touch are listed apart;
  - a waiting gate offers a Dismiss toggle per comment;
  - a "Review" tile joins the evidence strip;
  - the console reads "Sent back by review" on the gate's step;
  - a review agent's Input tab shows what it was given;
  - every view keeps its three states.
- **Fixtures**:
  - `independent-review.json`: a writer in a loop, three lenses and a dedupe, a gate with `review`, then a publish after the loop;
  - `review-composite.json`, called from a subflow in a test.
- **Specs and docs**:
  - tech-stack: Agent runtime, Tool layer, the findings model, Gate review, Workflow validation, UI design system, the templates and decisions-log rows;
  - design-language, for comments in a diff;
  - the roadmap's plan link;
  - `docs/security/security-model.md`;
  - `CHANGELOG.md`.

### Out of scope

- Posting review comments on the GitHub PR as line comments (an outward write): later, with 14.2 or 18.6.
- Lens instructions edited per workspace, and lenses as skills: **15.3**.
- Stopping a run whose review keeps failing (beyond rounds): **13.7**.
- Judging review quality with evals or an LLM judge: **17.2**.
- Review as evidence for earned autonomy: parked in `ideas.md`.
- Composites shipped by the platform to every workspace: the composite is a fixture a workspace stores ("Composites → Not yet").
- Why each hunk was written, beside the diff: **14.2**.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Shape | Visible nodes: a `parallel` of review agents and a `dedupe` reduce, made by one builder and shipped as a composite fixture | Chosen in the interview. One spec, many views (principle 1): the canvas, the run map and the console show lenses with no new view. It is built from existing primitives, so it is a composite, as the roadmap says |
| How independence is enforced | `AgentNode.review`: an engine-built input (spec, diff, evidence pack), read-only repo tools with no `artifacts.*`, no `reads`, the engine's findings schema, and reads of the writer's committed work | Chosen in the interview. Safe by construction (principle 2): the author cannot wire a lens to the writer's narrative by mistake |
| `of` unset | The latest writer before the node in run order | A stored composite cannot know its caller's node ids (6.5 renames them) |
| Where the send-back lives | `review` on the gate, the same path and rounds as `evidence`, with one counter per gate | Reuses 13.3. Lessons 13: two mechanisms that send work back count together and never use the last pass |
| Default threshold | `block_at: high` (high and critical go back) | The roadmap's "above a severity". Medium and below inform the person |
| A lens that fails | `settled` join; the gate pauses and names the lens | As evidence `error`: it is not the writer's fault, so a person decides |
| Comments placement | Mapped to the writer's changed file and line: a view zone in the diff, and a list that is the accessible path; untouched files listed apart | The roadmap says "on the lines they name". Monaco zones are not keyboard-reachable, so the list is primary |
| Leftover comments | Approver dismisses some; the rest become `## Review notes` in the PR through `notes_from` | Chosen in the interview (scope). The notes outlive the gate; mentions are neutralised (principle 5) |
| Lenses | Six presets; the templates default to correctness, security and performance | Chosen in the interview (scope). The default three are the roadmap's. Correctness and tests close the gaps left by 13.4 and 13.5 |
| Cross-provider | A lens's own `provider` and `model`, plus `review_provider` and `review_model` in the templates | Chosen in the interview. It costs little after 8.3 and is the roadmap's cross-model point |
| Templates | `review` option, default off, in SDD (both) and Plan, build and review | Chosen in the interview. The flows are unchanged with it off |
| Order of work | Spec and validation, then engine, gate, tools, templates, API and web, in one PR | Chosen in the interview, as 13.3 to 13.5 were |
| Real run | Read step by step with **GitHub Copilot** as the provider of every agent | Chosen in the interview. A one-off deviation from lessons rule 1's wording, recorded in the PR as 13.5 did. It also tests typed findings output on Copilot, which 8.3 left to a real run |

## Open questions

- **Default lenses in SDD.** SDD might want `tests` among its defaults, since it has criteria. The default keeps the roadmap's three, and `review_lenses` changes it per run.
- **Cost.** Each pass runs one agent per lens. Six lenses on `max_passes: 3` is 18 reviewer turns. They count on `agents_spawned` and the budget as any agent. The template's description says so.
- **Typed findings on Copilot** may fail where Claude does not (8.3: "the real run decides"). If the real run shows it, the fix and a lessons entry land in this PR.
- **Findings with no line** (a whole-file or whole-change finding) are shown at the top of their file, or in the "other files" list when they name no file.
