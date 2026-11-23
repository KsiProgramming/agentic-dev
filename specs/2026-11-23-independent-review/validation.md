# Validation: Independent review

## Done when (from roadmap)
> A review with three lenses sends a high-severity finding back to the writer, and its other findings reach the gate as comments on the lines they name

## Automated checks

- [ ] **Validation** (engine spec tests, fixtures):
  - `invalid_review` for a review agent with a write tool, `artifacts.read`, `reads` or an `output_schema`, or placed in an orchestrator's worker or a map;
  - `review_unknown_writer`;
  - `review_not_in_loop`;
  - `invalid_gate_review`;
  - `artifact_unknown` for `spec_from`, `notes` and `notes_from`;
  - `independent-review.json` and `review-composite.json` validate.
- [ ] **What each lens receives** (`test_review.py`, fake runtime, lessons 1):
  - its input has `## Spec`, `## Change` and `## Evidence` and nothing from the synthesizer or the writer's answer;
  - its tools are the five review read tools;
  - its context holds the request (lessons 8);
  - its reads without `node` return the writer's committed work;
  - `node_started.review` is set;
  - `of` unset resolves to the latest writer, also through a subflow.
- [ ] **Send-back and gate**:
  - a scripted `high` finding from one of three lenses completes the gate as `changes` / `source: "review"`, and the writer's next input holds it under `## Review`;
  - a pass with only `medium` and `low` findings pauses with them as comments mapped to their writer, file and line (`in_diff` true and false);
  - evidence and review share one counter and never use the loop's last pass (lessons 13);
  - a failed lens pauses and is named;
  - `dismissed` is stored and carried on `gate_decided`;
  - the notes artifact leaves dismissed comments out;
  - a resume at the gate makes the same decision.
- [ ] **PR notes**: `github.openPR` with `notes_from` adds `## Review notes` under the body, capped, with `@` mentions neutralised and HTML stripped.
- [ ] **Templates**:
  - SDD (both builders) and Plan, build and review validate with `review` on and off, and with `checks` and `test_first` where they exist;
  - with `review` off, the spec equals today's default;
  - what a lens, the lead and an engineer receive;
  - AC-5's worker test and the spec-file worker test pass with `review` on;
  - a 7.6 follow-up starts at `review_loop`;
  - `review_provider: copilot` resolves the lenses to Copilot, and a triggered run falls back to Claude.
- [ ] **API** (from `packages/api`):
  - `GET /runs/{id}/gate` carries `review`;
  - `POST /runs/{id}/approvals` accepts `dismissed` and refuses it with each `422` code;
  - the migration applies and reverts.
- [ ] **Web**:
  - `review-comments.test.tsx`: grouping, other files, Blocking, Dismiss, the three states, text-only messages;
  - the evidence strip's Review tile, with no empty cell;
  - "Sent back by review" from the recorded `review-run.json`;
  - the Input tab of a review agent.
- [ ] `uv run` lint, type check (strict) and tests for every touched package. Run sandbox tests by file, never `packages/sandbox/tests` as a whole.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`: axe (`a11y.spec.ts`) and layout screenshots (`layout.spec.ts`) of a gate with review comments in the dock, the Inbox and the review sheet.

## Manual / demo checks

- [ ] **Real run on GitHub Copilot** (chosen in the interview; every agent on Copilot):
  - **Setup.** Run Plan, build and review with `review` on, three lenses and `max_passes` 3, on a small Python repo with a SQLite helper and its tests. The request is "add a search by name endpoint".
  - **Expected:** a lens finds a `high` issue (for example SQL built from strings), the gate sends it back with no person, the lead's next pass gets it under `## Review` and fixes it, and the gate pauses with the remaining comments.
  - **In the console's Activity tab, check:**
    - each lens read the diff and the spec, not the synthesizer's text;
    - each lens's typed findings parsed on Copilot;
    - the lead's second-pass input names the finding.
- [ ] **At the gate:**
  - comments appear on their lines in the diff and in the list, at 375 and 1440 px, in light and dark;
  - one comment is dismissed from the keyboard;
  - Approve reads "1 dismissed";
  - the opened PR's body has `## Review notes` without the dismissed comment.
- [ ] The run's cost, with three lenses per pass, is recorded in the PR.

## Merge criteria

- [ ] All checks above pass in CI.
- [ ] The real Copilot run is read step by step, and the PR records it as a one-off deviation from lessons rule 1's wording (as 13.5 did). Anything the tests missed gets a `specs/lessons.md` entry in this PR.
- [ ] Specs updated in the same PR:
  - tech-stack sections and decisions-log rows;
  - design-language for comments in a diff;
  - the roadmap's plan link on 13.6;
  - `docs/security/security-model.md`;
  - a `CHANGELOG.md` entry under `## [Unreleased]`.
- [ ] Checked on a clean clone: `git status --short` lists every new file (lessons 12).
- [ ] No finding text is rendered as HTML anywhere (rule 11). No model output reaches the PR body with a live `@` mention.
