# Monitor shows dynamic children live

Roadmap phase: 6.4
Branch: plan/6.4-dynamic-children-monitor

## Context

6.1–6.3 (#157, #159, #161) gave the engine the `orchestrator`: a hub plans tasks, one worker runs per task, a failed task can make the hub replan (6.2), and the completed tasks' branches merge into one integration branch (6.3). The engine logs all of it (`plan_made`, `task_started`, `task_completed`, `replan_started`, `branch_integrated`, workers' events tagged `item` = the task's index; tech-stack → "Orchestrator (API contract)"), but the web shows none of it. Today:

- the console's timeline (`@/runs/timeline`) knows loops, maps, parallels and routers only, so a worker's steps are not grouped by task and the plan, rounds and integration are invisible;
- the run map and the builder canvas draw an orchestrator as one card with its worker hidden and not editable (tech-stack: "until the console and canvas learn it (6.4)").

6.4 makes the dynamic children visible, live, with their progress and cost, and lets the worker be drawn and edited on the canvas. It is web-only: the events already carry everything needed, and usage events carry `item`, so cost per task is derived on the client like a map item's. It depends on 6.1–6.3 (done) and unblocks 6.7 ("fix selected findings", whose fix tasks the user will watch here) and AC-2 (6.8, "run matches the drawn graph", which needs the worker drawn).

Principles that drive it:
- **Transparency** (mission 6): every agent action and cost is visible live; the hub's plan and its reason, each replan and each merge are actions.
- **Enterprise-grade, calm UI** (mission 8): tasks read as a story (plan → tasks → integration), the raw events stay one click away; what failed or needs attention is visible first.
- **One spec, many views** (mission 1): the canvas edits the worker through the same graph ops as any container body.
- **Repo content is data** (mission 5): task titles, instructions, the hub's reason and errors are model output, shown as text, never Markdown or HTML.
- Tech stack: the run console rules (step list, step keys, Output, run map) and the builder canvas rules in "UI design system"; display values from `@/components/display`; `design-language.md` for the look.

## Scope

### In scope
- **Timeline** (`@/runs/timeline`, `@/runs/spec-parents`): an orchestrator is a container. `plan_made` records the plan (tasks by id and title, `reason`, `round`); `task_started` / `task_completed` open and close a task (index, `task_id`, title, status incl. `dropped`, error); workers' events go into their task by `item` (and by the spec: `specParents` learns `kind: "orchestrator"` for nodes in its `body`); `replan_started` records the round's failed and dropped tasks; `branch_integrated` records the branch, merged, empty and conflicting tasks per round. The hub's agent turns stay the orchestrator's own step (its Activity). Older runs and runs without orchestrators fold exactly as today.
- **Step list:** tasks nest under the orchestrator like map items, grouped under a heading per round once there is a second round ("Round 2 · replanned after 1 failure"); each task row shows its title (as text), status, duration and cost (`Duration`, `Money`, `focusable={false}`); a dropped task is muted with a dashed-circle icon and "Dropped" (no status colour, like a skipped route); a task that conflicted at integration shows failed with "Conflicts with earlier tasks on …". The orchestrator's line reads "Planning" → "3 of 5 tasks · round 2" → "5 tasks · merged 4 into agent/…".
- **Step keys and URL:** a task's steps get the key `<orchestrator>.<task-id>/<node>` (the task alone: `<orchestrator>.<task-id>`), the same shape as its writer key, unique across rounds and stable as the run grows; `?step=` links to them; "which step is shown" follows the running task while live.
- **Orchestrator Output:** the plan per round (each task's title and status; not its instructions, which the events do not carry: `plan_made` has only ids and titles), the hub's `reason` as text, for a replan the failed and dropped tasks it was made from, and the integration (branch in mono, merged / empty tasks, conflicts with their paths as `TruncatedPath`); its tasks as rows that select their step, under a line that adds them up ("5 tasks · 2 rounds · 31 tool calls · 1m 12s · $0.84"). Usage tab lists each task's tokens and cost.
- **Run map:** the orchestrator card shows its progress ("Planning", "3 of 5 tasks · round 2", then "5 tasks · $0.84"); its worker body hangs off it to the right as a chain, as a map's body does; once planned, each task is a small card under the worker chain's header (status dot, task id in mono, title, duration and cost), selecting its step; dropped tasks dashed and "Dropped". Footer counts include tasks.
- **Canvas:** the orchestrator's `body` is drawn inside it and editable like a loop's or map's (`spec-tree`, `spec-graph`, `node-status`, `@/workflows/ops`, `@/workflows/edits`: Add a step after, Replace with…, Remove rules, "needs a body"); the palette and blocked-connection checks refuse in the body what validation refuses there (`not_allowed_in_orchestrator`), with the reason under the item. The browser's `applyOps` stays in step with the engine's through `schemas/fixtures/graph-ops.json` (new orchestrator cases).
- **Specs:** tech-stack "Run console" (step list, step key, Output, run map), "Builder canvas" and "Orchestrator (API contract) → In the web" updated; roadmap row gets its `[Plan]` link; changelog entry.

### Out of scope
- Any API or engine change (no per-task summary in `GET /runs/{id}`): the client derives everything from events. A server-side summary can come when another screen needs it.
- Showing tasks in the runs list or Inbox (only the console and canvas).
- Editing a plan or a running task (no human-in-the-loop on plans; Architect runtime adaptation is 9.8).
- Drawing nested orchestrators (still refused by validation).
- The `subflow` primitive's children (6.5).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where task progress and cost come from | Derived on the client from the event stream (`item`-tagged usage, `task_*` events), no API change | The same path as map items and parallel branches; events already carry it; a live run updates with no extra request (mission 6). |
| Task step key | `<orchestrator>.<task-id>/<node>` | Task ids are unique across rounds (6.2) and are already the writer key (`task_writer_key`); readable in a link and stable, unlike an index that a replan's numbering would make look odd. |
| Rounds in the step list | A heading per round only once there is a second round | A one-round run (most runs) reads like a map; a replan is visible exactly when it happened. |
| Dropped task | Muted, dashed-circle icon, "Dropped", no status colour | Colour means status only; a dropped task did not fail, as a route not taken did not (router rule). |
| Run map tasks | Task cards under the worker chain, appearing as they are planned | "Spawned workers appear" literally; the worker chain shows what each task runs, the task cards show how each went. |
| Canvas body | Edited like a loop's or map's body, with validation's body rules mirrored in the palette | 6.1 named the slot `body` for this; one way to edit any container (mission 1). |
| Fixtures | An orchestrator run's events recorded from the engine's fake-runtime test into `schemas/fixtures/`, read by the web tests | The web folds the engine's real event shapes; a change on either side breaks a test, not a demo. |

## Open questions
- None for 6.4. The roadmap's "Next up" line still names Milestone 4 at 4.8 (done); it should name Milestone 6, in its own PR with a changelog entry.
