# Plan: Monitor shows dynamic children live

Timeline first, then the views that read it, then the canvas, then the specs. Web-only; the project stays working after each group.

## 1. Event fixture from the engine
- [ ] `packages/engine/tests/test_orchestrator.py`: a fake-runtime run of a writing orchestrator with `replan` that has, in round 1, a completed, a failed and a dropped task and a merge conflict, and in round 2 a completed task; write its events (types, node ids, `item`, payloads, usage) to `schemas/fixtures/orchestrator-run-events.json`, and fail the test when the file is stale (as the other fixtures).
- [ ] A second, small fixture for a one-round run without writers, if the first does not cover the plain path.

## 2. Timeline learns the orchestrator
- [ ] `web/src/runs/spec-parents.ts`: `kind: "orchestrator"` for nodes in an orchestrator's `body`.
- [ ] `web/src/runs/timeline.ts`: orchestrator as a container; a `tasks` list on its step (index, `task_id`, title, round, status incl. `dropped`, error, steps, start/end), `plan_made` → plan and `reason` per round, `task_started` / `task_completed`, workers' events by `item` and spec parent, `replan_started` → round's failed and dropped, `branch_integrated` → integration per round (a conflicting task marked failed with its paths).
- [ ] Usage and duration per task (sum of its steps), and the orchestrator's totals (hub turns + tasks).
- [ ] `timeline.test.ts`: the fixtures fold into the right rounds, tasks, statuses and costs; a partial stream (live, mid-round) folds too; events before 6.1 and runs with no orchestrator fold unchanged.

## 3. Step list, step keys and the selected step
- [ ] `web/src/runs/console/step-entries.ts`: task scopes keyed `<orchestrator>.<task-id>`; round headings when there are two rounds or more; task rows with title (text), status, `Duration`, `Money`, `focusable={false}`; dropped rows muted with the dashed-circle icon; the orchestrator's one-liner ("Planning", "3 of 5 tasks · round 2", "5 tasks · merged 4 into …").
- [ ] `step-list.tsx` / `item-name.ts` / `step-status.ts`: the orchestrator kind and the task names; "which step is shown" follows the running task.
- [ ] `step-output.tsx`: an orchestrator's Output: plan per round (titles, statuses, instructions on demand, as text), hub reason, replan inputs (failed / dropped), integration (branch in mono, merged / empty, conflicts with `TruncatedPath`), its tasks as rows that select their step, the summary line.
- [ ] `step-usage.tsx`: each task's tokens and cost; `step-input.tsx`: the orchestrator's settings (hub, `max_workers`, `max_concurrency`, `replan`) and a task's input (its task as text).
- [ ] Tests: `step-entries.test.ts`, `step-view.test.tsx` for the orchestrator Output, keys and the dropped / conflict rows.

## 4. Run map
- [ ] `web/src/runs/graph/spec-tree.tsx`, `spec-graph.ts`, `node-status.ts`: the orchestrator's body hangs off it as a chain; the card's progress line; task cards (status dot, id in mono, title, duration, cost) under the worker chain, dashed for dropped; selecting one shows its step; the footer counts tasks.
- [ ] Accessible names include the visible text plus status and kind words (as other cards); `aria-pressed` on the shown task.
- [ ] Tests in the run map's suite with the fixtures.

## 5. Canvas: the worker body
- [ ] `web/src/workflows/ops.ts`: `addNode` into an orchestrator's `body` (slot taken, empty body is a missing issue), `removeNode` leaves it empty as a loop's; new cases in `schemas/fixtures/graph-ops.json` and the engine's ops test reading them.
- [ ] `web/src/workflows/edits.ts`: `placeOf` / `stayReason` for the body ("An orchestrator needs a body; replace it instead."); the palette and `blockReason` refuse kinds `not_allowed_in_orchestrator` in the body, with the reason.
- [ ] Canvas draws the body inside the orchestrator card (`SpecTree`); side panel works on body nodes unchanged.
- [ ] Tests: `ops.test.ts`, `edits.test.ts`, the canvas suite.

## 6. Specs, demo and changelog
- [ ] `specs/tech-stack.md`: Run console (step list, step key, Output, Usage, run map), Builder canvas, Orchestrator → "In the web"; decisions-log rows from requirements.
- [ ] `specs/roadmap.md`: `[Plan]` link on 6.4.
- [ ] `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Live demo on Claude (see validation), screenshots at 375 and 1440 px, light and dark, for the PR.
