# Plan: AC-2 end-to-end: a canvas flow with parallel, orchestrator, loop and gate

Order chosen with the user: the engine check first, then the browser, then the template's real run. The project stays green after each group.

## 1. The AC-2 spec and what its agents receive

- [x] Add `packages/engine/tests/fixtures/specs/valid/ac2-plan-build-review.json`: the flow in `requirements.md` (ids `explore`, `code_analyst`, `test_analyst`, `review_loop`, `pass`, `implement`, `engineer`, `synthesizer`, `reviewer`, `approve_pr`, `publish`), with real instructions and tools.
- [x] Test that it validates (`POST /workflows/{id}/validate` codes empty) and compiles.
- [x] "What agents receive" test (lessons rule 1, fake runtime): for each agent, its input, tools, run context and the node id its tool calls go out as. Settle the open question: does the lead's input hold the request? Pick the fix if not, and write it in tech-stack (and lessons, if it changes what every agent gets).
- [x] Assert the readers after `implement` (`synthesizer`, `reviewer`) read its integration branch (lessons rule 5), and `approve_pr` shows the integration branch as the one writer.

## 2. The "run matches the graph" check

- [x] `packages/engine/src/agentic_engine/conformance.py`: `trace_mismatches(spec, events) -> list[Mismatch]` with the four rules in `requirements.md` (unknown node, drawn node with no outcome, order, version). `Mismatch` names the node id, its spec path and a sentence.
- [x] Unit tests on hand-made event lists, one per rule, including: a parallel branch that ends after the join, a loop iteration out of order, a route not taken (no mismatch), a run stopped at the gate (later nodes "not reached", no mismatch), an orchestrator task id (allowed), a node id not in the spec (mismatch).
- [x] Engine end-to-end test on the fake runtime: the AC-2 spec runs with the reviewer answering `changes` then `ok`, the hub planning two tasks per pass, the gate approved and a fake `openPR`; `trace_mismatches` is empty and the run has two loop iterations, four tasks and one PR.
- [x] Run the check over the existing run fixtures (`orchestrator-run.json`, `orchestrator-loop-run.json`, `audit-fix-run.json`, `subflow-run.json`) as a regression: they must match their specs too.
- [x] Export `schemas/fixtures/ac2-run.json` (spec plus events) from that run, with a staleness test like `audit-fix-run.json`.

## 3. Build it on the canvas (browser e2e)

- [ ] `web/e2e/ac2.spec.ts`: from Workflows → New workflow → Blank canvas, build the AC-2 flow by menu items only:
  - starter agent → Add a step after (agent) → Wrap in… Parallel (`explore`);
  - Add a step after → Orchestrator (`implement`), worker set in the side panel; Add a step after (agent `synthesizer`, agent `reviewer`, with its `output_schema`);
  - Wrap in… Loop over `implement` through `reviewer`, `until` and `max_iterations` in the side panel;
  - Add a step after → Gate, then Tool `github.openPR`;
  - each agent's role, instructions and tools in the side panel. The status line reads "Ready to run"; Save makes version N.
- [ ] Run this version (`WorkflowRunSheet`) on the stack's fake agents (`fit_schemas`): the hub plans one task and the reviewer approves the first pass, so the browser run has one loop iteration; two passes, the second built on the first, are covered by the engine tests (`test_ac2.py`). Approve the gate from the approval dock.
- [ ] Compare the run map with the canvas of version N: the same cards joined by the same edges (wraps aside), the orchestrator's one task, every card with the status its events give.
- [ ] The same build once by keyboard only (Tab, Enter, arrow keys in menus), shortened to the parallel, orchestrator, loop and gate.
- [ ] Each gap found (a menu item missing, an edit refused, a card drawn somewhere else in the run map than on the canvas) gets its own task here, a unit test and a fix, and a line in tech-stack → Builder canvas or Run console if it changes a rule.

## 4. The template

- [x] `packages/engine/src/agentic_engine/templates/plan_build_review.py`: `PlanBuildReviewParams` (models, `max_passes`) and `build_plan_build_review_spec`, building the fixture's flow; register it in `templates/__init__.py` with `requires=("claude", "github")` and a description that says it writes and opens a PR after approval.
- [x] Template tests: every option validates; only `engineer` writes; only `publish` publishes and it comes after `approve_pr`; every agent that checks code has read tools; no placeholder instructions; `input` is required and named.
- [x] The engine end-to-end test of group 2 also runs on the template's default spec.
- [ ] Regenerate `schemas/fixtures/node-types.json` and the OpenAPI client if they change; the start screen's gallery shows the template (check the start-screen e2e and layout screenshots).

## 5. Specs and docs

- [x] `specs/tech-stack.md`: a "Plan, build and review template" section (as "Audit codebase template"), the conformance helper under "Testing & quality", and decisions-log rows (template vs fixture; check as a helper, not an endpoint; the answer to the open question).
- [x] `specs/roadmap.md`: 6.8's row links this plan; the Acceptance criteria map keeps AC-2 → 6.8.
- [ ] `specs/lessons.md`: an entry for anything the real run shows that tests did not.
- [x] `CHANGELOG.md`: an entry under `## [Unreleased]`.

## Found while building

- [x] The lead lost the request after the parallel and in later passes: `RunContext.request` (lessons rule 8).
- [x] `GET /templates` did not say a template needs an input, so the gallery's sheet could not ask for it: `TemplateOut.input`, and the sheet shows the field.
- [x] The stack's fake agents only echoed, so no orchestrator could run in an e2e: `AgentRequest.output_schema` and `FakeRuntime(fit_schemas=True)`.
- [x] The canvas and the run map had no way to compare their edges: `data-from` / `data-to` on each drawn edge; `RunMap` takes `layout` for tests.

## 6. Real run with Claude

- [ ] `AGENTIC_RUNTIME=claude` on a small real repo, from the gallery's template and once from the canvas-built workflow; read each step's Activity in the console (see `validation.md`), fix what it shows, and record it in lessons.
