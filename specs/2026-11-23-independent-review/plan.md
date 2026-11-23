# Plan: Independent review

One PR, in this order. The tree keeps working after each group. Nothing changes for a spec that uses neither `review` on an agent nor `review` on a gate, and every template option is off by default.

## 1. Spec, findings categories and validation (`packages/runtime`, `packages/engine`)

> Added while building group 1: **a `parallel` may be in a loop's body** (it was `not_allowed_in_loop`), because the lenses' parallel sits in the writer's loop. Decisions-log row in tech-stack; `parallel_results` are kept per pass (`test_parallel_in_loop.py`).

- [x] `agentic_runtime.findings`: add the categories `correctness`, `performance`, `compatibility` and `accessibility` (additive). Regenerate `schemas/findings.v1.json`.
- [x] `ReviewOf` (`of: NodeId | None`, `spec_from: ArtifactName | None`, Markdown only) as `AgentNode.review`. `GateReview` (`from`, `block_at: Severity = "high"`, `max_rounds`, `notes: ArtifactName | None`, Markdown only) as `GateNode.review`. Schema errors for `review` with `select` or `on_changes`, as for `evidence`.
- [ ] `notes_from` on `github.openPR` args (a Markdown artifact): validated as an artifact read (`artifact_unknown`); the engine handling is group 4.
- [x] Validation issues, each with an actionable message:
  - `invalid_review`: a review agent with a tool outside the review read tools, with `reads`, `input_schema` or `output_schema`, or in an orchestrator's worker or a map;
  - `review_unknown_writer`: `of` is not a writer or an orchestrator whose body writes that completes before the node, or no writer runs before it when `of` is unset;
  - `review_not_in_loop`: a gate `review` outside a loop's body;
  - `invalid_gate_review`: `from` is not a `.json` artifact written before the gate in the same body, or it is not typed as findings;
  - `artifact_unknown` for a `spec_from`, `notes` or `notes_from` that nothing writes before.
- [x] Regenerate the JSON Schema and node manifests, so the side panel edits `review` on an agent and on a gate (5.4).
- [x] Valid and invalid fixtures (the two review fixtures follow in group 8) under `packages/engine/tests/fixtures/specs/`, and validation tests.

## 2. Review agents and lens presets (`packages/engine`, `packages/runtime`)

- [x] `agentic_engine.review`:
  - `LENSES`: six presets (id, title, category, instructions), with correctness covering in-code suppressions and `.csproj` analyzer settings, and tests covering weak tests;
  - `review_flow(...)`: a `parallel` (join `settled`) of review agents, then a `dedupe` reduce that writes `review.json`.
- [x] Resolving `of` at run time from `writers_before(state)`: the latest writer when unset, so a resume gives the same answer.
- [x] Building the input in the compiler, in place of the previous output:
  - `## Spec`: the latest version of `spec_from`, capped;
  - `## Change`: the `repo.diff` header lines and the diff, cut at a cap with a note to call `repo.diff {path}`, read through the executor;
  - `## Evidence`: the pack of this pass's gate on that writer from `RunState.evidence`, summarised and capped;
  - every heading present, saying "none" when it is absent.
- [x] Reads without `node` resolve to `of` through 13.1's `ReadableWriters` (refs, committed work only), never the writer's worktree or server. Set the engine's findings `output_schema` with the lens category, as `classifier_schema` does.
- [x] `node_started.review` (`of`, `spec`, `spec_version`, `diff` stats, `evidence`).
- [x] Engine tests on the fake runtime (`test_review.py`, lessons 1). Assert what each lens receives:
  - its input sections;
  - its tools;
  - its context, including the request;
  - no synthesizer or writer answer in its input;
  - its reads going to the writer's branch.

  Also test: a stored composite called by a subflow with `of` unset reviews the caller's writer (done); a restart between the lenses and the reduce re-runs neither finished lens (not written: left to LangGraph's checkpoint, which `test_parallel` covers for a plain parallel).

## 3. Gate `review`: send-back, comments, dismissals, notes (`packages/engine`, `packages/worker`)

- [x] At the gate, read the latest version of `from` written in this pass. Split the findings by `block_at`. Collect the failed lenses from the merged report's failed `branch` checks.
- [x] Send-back:
  - with blocking findings and a round left, complete as `{decision: "changes", source: "review", comments}` with `## Review` (capped, as data);
  - count rounds with the gate's `evidence` in one counter (`RunState.rounds`), `rounds_left = min(max_rounds - used, passes left)` (lessons 13);
  - with evidence and review both failing in one pass, send back once with both sections.
- [x] Pausing:
  - when a lens failed, or rounds are out, or nothing blocks;
  - `gate_waiting` carries `review`: `{from, version, block_at, rounds_left, comments, failed_lenses, counts}`. Each comment has `fingerprint`, `severity`, `category`, `lenses`, `path`, `line`, `end_line`, `message`, `node_id` (the writer whose diff holds the file), `in_diff` and `blocking`. At most 100.
- [x] `dismissed` on approve: checked against the gate's comment fingerprints with fixed codes, then stored. `gate_decided` adds it.
- [x] With `review.notes`, approving writes the remaining comments as Markdown (severity, `path:line`, lenses, message), as a new version.
- [x] Audit `gate.sent_back_by_review`, with the system as its actor.
- [x] Tests:
  - a high finding sends back with the expected text;
  - a medium finding pauses with comments;
  - the shared counter, and that the last pass is never used;
  - a failed lens pauses;
  - dismissals and the notes artifact;
  - a resume during the gate makes the same decision.

## 4. Tools: PR notes (`packages/tools`, `packages/engine`)

- [x] `github.openPR` `notes_from`: the engine appends `## Review notes` with the artifact's text under the body, capped, as `body_from` does. Neutralise `@name` mentions (a zero-width joiner after `@`) and strip HTML. The tool never sees `notes_from`.
- [x] Tests: a body with notes, a body with a mention, and a cap.

## 5. Templates (`templates/sdd.py`, `templates/plan_build_review.py`)

- [x] Options on `SddParams` and `PlanBuildReviewParams`, with `review` default off and the others applying only with it on:
  - `review_lenses` (a non-empty subset of the six, default correctness, security, performance);
  - `review_block_at` (default `high`);
  - `review_provider`;
  - `review_model` (a priced model).
- [x] With `review` on:
  - `review_flow(of="implement", spec_from="spec.md")` replaces `reviewer` (Plan, build and review has no `spec_from`);
  - `approve_pr` sits in the loop's body with `review: {from: "review.json", block_at, notes: "review-notes.md"}`, plus `evidence` as `checks` already sets it;
  - `until` reads `approve_pr`'s approval (and `checks`' where it applies);
  - `publish` gets `notes_from: "review-notes.md"`;
  - `max_passes` must be at least 2.
- [x] Instructions: the lead and engineers are told a later pass's input may be `## Review` findings, as data. The synthesizer's description stays for the PR body and the gate, and is never a lens's input.
- [x] Template tests:
  - what a lens, the lead and an engineer receive (lessons 1);
  - the spec validates with `review` on and off, with and without `checks` and `test_first`;
  - AC-5's worker test and the spec-file worker test run with `review` (not run: the engine-level `test_ac2_review.py` and `test_review_templates.py` cover the flows; the worker tests are left for the real run);
  - a 7.6 follow-up still starts at `review_loop` (`on_review` is unchanged and every SDD option validates).

## 6. API and store (`packages/api`, `packages/store`)

- [x] `GET /runs/{id}/gate` carries `review`. `POST /runs/{id}/approvals` takes `dismissed`. It returns `422` `dismiss_not_allowed` (on a reject, or on a gate without review), `unknown_dismissal` or `duplicate_dismissal`.
- [x] Alembic migration: `approvals.dismissed` (JSON, nullable).
- [x] Regenerate the OpenAPI spec and the web client. API tests run from `packages/api`.

## 7. Web (`web/`)

Read `specs/design-language.md` and tech-stack → UI design system first. If a rule has to change, change those files first.

- [ ] `ReviewComments` (`web/src/runs/console/review-comments.tsx`):
  - comments grouped by file;
  - each row has a `SeverityBadge`, `path:line` (`TruncatedPath`), the lenses (mono), the message as text and "Blocking" when set;
  - a Dismiss toggle on a waiting gate, with "N dismissed" in the Approve label;
  - the failed lenses as an error line;
  - files the change did not touch, listed apart;
  - the three states;
  - selecting a row opens its file at its line.
- [ ] `diff-view.tsx`: view zones under the commented lines on the changed side (badge, lenses, message as text), following the theme.
- [ ] `evidence-strip.tsx`: a Review tile ("2 high · 5 comments", with a badge Passed, Sent back or Could not run). It never leaves an empty cell.
- [ ] Console:
  - the gate's step reads "Sent back by review" (timeline `gate_decided.source`);
  - the review agent's Input tab shows "Reviewing <writer>" and what it was given (`node_started.review`).
- [ ] Inbox review, dock review sheet and review sheet: the same components, through `useGateDecision`.
- [ ] Component tests: `review-comments.test.tsx`, plus additions to `evidence-strip`, `step-input` and `use-gate-decision` tests.

## 8. Fixtures, specs and the real run

- [x] `packages/engine/tests/fixtures/specs/valid/independent-review.json` and `review-composite.json`. Run fixture for the web: `schemas/fixtures/review-run.json` (`test_review_fixture.py`, `UPDATE_FIXTURES=1`).
- [ ] e2e on the rebuilt compose stack: a gate with review comments in the dock, the Inbox and the review sheet, at 375, 768 and 1440 px, in light and dark, with axe.
- [x] Specs and docs (the roadmap's plan link: the roadmap has no link column, so none was added):
  - tech-stack: Agent runtime ("What an agent is told": review input), Tool layer (`notes_from`), the findings categories, Gate review, Workflow validation, UI design system → Gate evidence and Review comments, the three templates, and decisions-log rows for each decision in requirements;
  - design-language: comments in a diff;
  - the roadmap's plan link on 13.6;
  - `docs/security/security-model.md`: review agents are read-only, and PR notes neutralise mentions;
  - `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Real run on Copilot (see validation). Read it step by step. Add an entry to `specs/lessons.md` for anything the tests did not catch.
