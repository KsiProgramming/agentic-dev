# Validation: Monitor shows dynamic children live

## Done when (from roadmap)
> Spawned workers appear with progress and cost

Made checkable: while an orchestrator runs, each planned task appears in the step list and the run map as soon as it is planned, with its status, duration and cost updating live; the orchestrator shows how many tasks are done and in which round; a replan, a dropped task and a merge conflict are visible; the worker is drawn and editable on the canvas.

## Automated checks
- [ ] Engine: `test_orchestrator_fixture.py` writes and checks `schemas/fixtures/orchestrator-run.json` (stale fixture fails); ops fixture cases for the orchestrator body pass on both sides.
- [ ] Vitest, timeline: the 2-round fixture folds into tasks with the right round, status (`completed`, `failed`, `dropped`, a conflict as `failed` with paths), duration and cost; the orchestrator's totals equal hub + tasks; a stream cut mid-round folds into running tasks; pre-6.1 events and orchestrator-free runs are unchanged (existing tests stay green).
- [ ] Vitest, step list and keys: task rows under the orchestrator keyed `<orch>.<task>/<node>`, round headings only with two rounds, dropped row muted with no status colour, the orchestrator's one-liner at each stage.
- [ ] Vitest, Output / Usage: plan, reason, replan inputs and integration shown as text (a `<b>` in a task title renders as text); task rows select their step; per-task tokens and cost.
- [ ] Vitest, run map: worker chain under the orchestrator, task cards with status and cost, dashed dropped cards, accessible names contain the visible text.
- [ ] Vitest, canvas: `ops.test.ts` / `edits.test.ts` add, replace and remove in an orchestrator body; a gate or loop is refused in it with the reason.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test`; `uv run pytest packages/engine` (and the repo's Python lint), run locally.

## Manual / demo checks
- [ ] Live demo on Claude: a stored workflow with an orchestrator (hub plans 3 doc tasks over a small repo, worker = one agent writing a file, `replan: {on: failure, max_rounds: 1}`), started from the builder's Run. In the console, the orchestrator reads "Planning", then 3 tasks appear under it within 1 s of `plan_made`, each ticking its duration and cost; the orchestrator's line counts done tasks; at the end the Output shows the plan, the reason and the integration branch with 3 merged tasks; the Graph tab shows the same 3 task cards.
- [ ] Open a task's step by its `?step=<orch>.<task>/<node>` link in a new tab: the same step opens.
- [ ] On the canvas, open that workflow: the worker is drawn inside the orchestrator; replace it with a sequence of two agents, save, and the version diff shows the change.
- [ ] Look at the console and canvas at 375 and 1440 px, light and dark; no horizontal page scroll.
- [ ] Screenshots of the live console and the run map in the PR.

## Merge criteria
- [ ] All automated checks above pass locally (CI minutes are limited; CI runs on the PR, not watched step by step).
- [ ] tech-stack (Run console, Builder canvas, Orchestrator → In the web, decisions log), roadmap `[Plan]` link and `CHANGELOG.md` updated in the same PR.
- [ ] No API or engine behaviour change beyond the test fixture; no colour outside tokens, no JSON in a table cell, agent text rendered as text.
- [ ] The phase is marked done by CI on the PR branch.
