# `orchestrator` primitive

Roadmap phase: 6.1
Branch: plan/6.1-orchestrator-primitive

## Context

Milestone 6 adds dynamic orchestration: work whose subtasks are not known until an agent has looked at it. Every primitive so far fans out over something fixed in the spec (`parallel`'s branches) or computed by an expression (`map`'s `over`). The `orchestrator` lets a **hub agent** plan N subtasks at runtime and the engine spawns **one worker per subtask** (product spec §4.2: hub agent, plan schema, worker sub-flow, max workers, max depth, replan policy).

It builds on what is done: `map`'s `Send` fan-out and per-item checkpoints (1.10), the policy limits (3.2), typed ports (4.2, the plan is checked like the router's classifier answer), `reduce` sources (4.5), the router's checkpointed choice (4.6) and the node manifests and builder (5.3–5.5). It unblocks replan (6.2), the integration branch (6.3), live dynamic children in the monitor (6.4), "fix selected findings" (6.7) and AC-2 (6.8).

Principles that drive it:
- **Open, but safe by construction** (mission 2): the plan is bounded by `max_workers`, `agents_spawned`, `agents_alive` and `max_depth`, checked at validation and again when the plan is made.
- **Humans approve irreversible actions** (mission 3): worker writers commit only to their own branches; nothing is pushed or published from them in this phase.
- **Repo content is data** (mission 5): a task's text reaches its worker as input, never as the worker's instructions.
- **Transparency** (mission 6): the plan and every worker's events are in the log.
- Tech stack: LangGraph `Send` for dynamic fan-out (Engine row, decisions log "Engine"); CEL is not used for the plan, an engine-made `output_schema` is (as the router's `classifier_schema`).

## Scope

### In scope
- **Spec model** `OrchestratorNode`: `{type: "orchestrator", id, hub: {role, instructions, provider?, model?}, body: <worker node>, max_workers, max_concurrency, writes?}`.
  - `body` is the worker: one `agent` or a `sequence` of `agent`/`tool` nodes (no gate, publisher, repo creation, map, parallel, loop, router or orchestrator inside it in 6.1).
  - `max_workers` 1 to the platform's `agents_spawned`; `max_concurrency` 1 to `agents_alive`.
- **The plan**: the hub is one agent turn (role `hub`) whose `output_schema` is made by the engine: `{tasks: [{id, title, instructions}], reason}`, `tasks` at most `max_workers`, task ids unique slugs. An off-schema answer fails the orchestrator as a typed port (4.2) with `node_failed`'s `port`. An empty plan completes with no workers.
- **Workers**: one per task, at most `max_concurrency` at a time, each on input `{task: {id, title, instructions}, input: <the orchestrator's input>}` as JSON. Their agents get their own instructions from the spec; the task arrives as data.
- **Writer workers**: a worker agent with write tools gets its own worktree and branch, made when its task starts: writer key `<orchestrator>--<task>`, branch `agent/<run>/<orchestrator>--<task>`. The repo tools route its calls by that key. A gate after the orchestrator shows every worker's changes (gate review learns the dynamic writers from the run state) and commits edits to their branches.
- **Output**: the workers' outputs in task order; a `reduce` may name an orchestrator in `from` (source ids are the task ids). `writes` on the orchestrator stores its output as an artifact.
- **Limits**: the hub and every worker's agents count on `agents_spawned` when the plan is made (over it: `policy_limit_exceeded`, a clean stop); workers wait for `agents_alive` slots; an orchestrator is one level of `max_depth`.
- **Resume**: the plan is checkpointed in `RunState.plans` (orchestrator id → tasks), so a resumed run never asks the hub again; each task is checkpointed like a map item.
- **Events**: `node_started` (`max_workers`), the hub's agent events, `plan_made` (`tasks: [{id, title}]`, `reason`), workers' events tagged `task: <id>` (as a map item's `item`), the orchestrator's `node_completed` (`tasks`, `completed`).
- **Validation** issues: `not_allowed_in_orchestrator` (on the forbidden node in the body), `reference` for a publisher whose `from_node` is an orchestrator or a node in its body, policy issues for `max_concurrency` and depth.
- **Contract in tech-stack** ("Orchestrator (API contract)") and a decisions-log row per choice below; the `schemas/` JSON Schema export.
- **Node manifest** (category `flow`, icon `network`) and regenerated `schemas/fixtures/node-types.json`, so the builder palette offers it with no web change.

### Out of scope
- Replan on failure (6.2): one failed worker fails the orchestrator; there is no `replan` field yet.
- Publishing worker branches (`github.openPR` from an orchestrator) and merging them into one integration branch (6.3).
- A console view of the plan and live workers beyond what the step list already shows for tagged steps (6.4).
- Orchestrators inside a worker, a map, a parallel branch or a loop body (nested orchestration; `max_depth` 2 is kept for when it is allowed).
- A worker library (several worker kinds the hub chooses from): one worker template per orchestrator.
- Run console, builder or web code changes, apart from what the manifest gives for free.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Plan shape | An engine-made `output_schema` on the hub turn (`orchestrator_plan_schema`), checked as a typed port | Same path as the router's classifier: no new parser, a hub cannot plan more than `max_workers` or an off-shape task. |
| Task text | Passed to the worker as its input (data), never appended to its instructions | Mission 5; the worker's instructions stay the ones a human wrote and reviewed. |
| Worker slot name | `body`, as on `map` and `loop` | The graph ops (`at {parent}`), `SpecTree` and validation already handle a container's single `body`, so the builder draws and edits it with no web change. |
| Execution | One `Send` per task, each task run with the in-process runner (`_run_inline`), per-task checkpoints | Reuses the map's fan-out and resume path; no new LangGraph node per task. |
| Writer workers | Allowed; a worktree and branch per task (`<orchestrator>--<task>`), made when the task starts; publishing them refused until 6.3 | User's choice for 6.1. The branch keeps writers apart; without an integration branch one PR cannot hold them, so the publish rule stays strict. A gate can still review them. |
| Failed worker | Fails the orchestrator (running workers `node_cancelled`) | Replan is 6.2; a partial result that looks complete is worse than a clear failure. |
| Depth | An orchestrator is a level of `max_depth`, and none may nest in 6.1 | Product spec's "orchestrator nesting depth"; nesting dynamic fan-outs multiplies spawned agents and is not needed by 6.2–6.8. |

## Open questions
- The `NodeId` pattern must accept `<orchestrator>--<task>` as a writer key and branch segment; if it does not, the key becomes `<orchestrator>.<task>` (confirmed in task group 1).
- The roadmap's "Next up" line still names Milestone 4 at 4.8 (done in #156); it should name Milestone 6, in its own PR with a changelog entry.
