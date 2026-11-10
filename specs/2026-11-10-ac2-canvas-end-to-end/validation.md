# Validation: AC-2 end-to-end: a canvas flow with parallel, orchestrator, loop and gate

## Done when (from roadmap)

> Run matches the drawn graph

Made checkable: a flow with a `parallel`, an `orchestrator` inside a `loop`, a `gate` and `github.openPR`, built from a blank canvas by menu items, saved and run, gives a run whose every step is a node drawn in that version at the same place, in the spec's order, and whose every drawn node ran, was not on the route taken or was not reached, with why. `trace_mismatches` returns nothing for it, and the run map and the canvas of that version show the same nodes at the same places.

## Automated checks

- [ ] **Engine: AC-2 spec**
  - `ac2-plan-build-review.json` validates with no issue and compiles.
  - What agents receive (lessons rule 1), fake runtime: each analyst's input is the request and its tools are the repo read tools; the lead's input holds the request and the analyses (the open question's answer), its tools are the read tools only; each `engineer` gets its task, has the write tools, and its calls go out as `implement.<task>`; `synthesizer` and `reviewer` read the integration branch; `approve_pr` shows it as the one writer.
- [ ] **Engine: conformance check**
  - one unit test per rule: unknown node, drawn node with no outcome, out-of-order sequence step, a branch ending after its parallel, loop iterations out of order, wrong version;
  - no false mismatch for a route not taken, a run stopped at a gate, orchestrator tasks and replan rounds;
  - the existing run fixtures (`orchestrator-run`, `orchestrator-loop-run`, `audit-fix-run`, `subflow-run`) all match their specs.
- [ ] **Engine: end to end on the fake runtime.** The AC-2 spec and the template's default spec each run with the reviewer answering `changes` then `ok`: two loop iterations, two tasks per pass merged on one integration branch, the gate approved, one PR opened, and `trace_mismatches` empty. `ac2-run.json` is fresh (its test fails when stale).
- [ ] **Template**
  - every `PlanBuildReviewParams` combination validates;
  - only `engineer` writes, only `publish` publishes, `publish` is after `approve_pr`;
  - every agent that checks code has read tools, no instruction is the builder's starter text, `input` is required and named.
- [ ] **Browser e2e (`web/e2e/ac2.spec.ts`)**
  - builds the flow from Blank canvas by menu items only, reaches "Ready to run" and saves;
  - runs that version, approves the gate from the approval dock, and the run ends Completed with a PR link;
  - the run map's cards and the canvas's cards of that version have the same ids at the same places, the loop shows two iterations and the orchestrator its tasks, each card with the status its events give;
  - the shortened build works by keyboard only.
- [ ] **Existing suites still pass**: start screen (the new template in the gallery), builder, composite, console, a11y and layout specs.
- [ ] **Lint and types**
  - `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict) and `uv run pytest` are green;
  - in `web/`, `pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e` are green;
  - `schemas/fixtures` and the OpenAPI client regenerated with no diff left.

## Manual / demo checks

- [ ] **Real run with Claude** (`AGENTIC_RUNTIME=claude`, lessons rule 1) on a small real repo, started from the "Plan, build and review" template with a request such as "Add input validation to the signup form, with tests":
  1. `explore`: both analysts ran at the same time; their Activity shows they read the files the request touches.
  2. `implement`, pass 1: the lead's Activity shows it read the code and that its input had the request; it plans at most two tasks on different files. Each engineer's Activity shows it changed only its task's files and committed. The Output shows the tasks merged on the integration branch.
  3. `synthesizer` and `reviewer` read the merged code (their tool calls find the engineers' changes). If the reviewer asks for changes, pass 2's lead plans only what the feedback asks, on top of pass 1's work.
  4. `approve_pr` shows one diff with every pass's work. Approve it; the PR on GitHub holds the change and the synthesizer's description.
  5. The run map shows every step where the template's canvas draws it.
- [ ] **The canvas-built workflow** from the browser e2e, saved in a real workspace and run once with Claude, reads the same way in the console.
- [ ] Any surprise from the real runs is fixed and recorded in `specs/lessons.md`.

## Merge criteria

- [ ] All automated checks above pass locally (CI minutes are limited: run them locally, do not wait on CI).
- [ ] `specs/tech-stack.md` has the template section, the conformance helper and the decisions-log rows; `specs/roadmap.md` links this plan from 6.8; `CHANGELOG.md` has an entry under `## [Unreleased]`.
- [ ] The open question is answered and recorded in tech-stack (and lessons if every agent's context changed).
- [ ] No secret, key or token in events, fixtures or logs.
