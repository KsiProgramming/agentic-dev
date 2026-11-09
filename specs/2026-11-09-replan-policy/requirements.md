# Replan policy (on-failure)

Roadmap phase: 6.2
Branch: plan/6.2-replan-policy

## Context

6.1 (#157) added the `orchestrator`: a hub plans N tasks and the engine runs one worker per task. When a worker fails today, the other workers are cancelled and the orchestrator fails (tech-stack decisions log, "A failed task (6.1)"). The product spec lists a **replan policy** among the orchestrator's parameters (`"replan": "on-failure"`, product-spec §4.2 and §4.5): when a worker fails, the hub sees what happened and plans the remaining work, within limits.

6.2 adds that policy. It depends only on 6.1 (done). It unblocks "fix selected findings" (6.7), where one failing fix should not throw away the others, and AC-2 (6.8). The console view of rounds is 6.4.

Principles that drive it:
- **Open, but safe by construction** (mission 2): replans are bounded by `max_rounds`, `max_workers`, `agents_spawned` and wall time, checked at validation and again when each round is planned.
- **Repo content is data** (mission 5): a failed task's error and the completed tasks' outputs reach the hub as input, never as instructions.
- **Transparency** (mission 6): every round's plan, and why it was made, is in the event log.
- **Nothing is lost** (mission 9): work that completed is kept; a replan never re-does it.
- Tech stack: LangGraph `Send` fan-out (Engine row); the plan stays an engine-made `output_schema` (decisions log, "Orchestrator plan (6.1)").

## Scope

### In scope
- **Spec**: `OrchestratorNode.replan: {on: "failure", max_rounds: 1..3} | None`. Unset keeps 6.1's behaviour exactly (cancel the others, fail the orchestrator).
- **Settle, then replan** (the user's choice): when a task fails, no new task starts; tasks already running finish; tasks not started end `dropped` (a new status on `task_completed`, not a failure). When the round has settled, the hub is asked again.
- **The replan turn**: one hub turn with the same role and instructions, then how to replan (`hub_replan_instructions`), on input `{input, round, tasks: [{id, title, status, output?, error?}]}` as JSON (data). Same plan `output_schema`, with `tasks` at most `max_workers` minus the tasks completed so far. An empty replan ends the orchestrator: completed if at least one task completed, otherwise failed with the last error.
- **Task ids are unique across rounds**: a replan may not reuse any earlier task id (failed, dropped or completed). This keeps writer keys and branches (`<orchestrator>.<task>`) apart, so a failed writer's branch is left as it was. Reuse fails the orchestrator as a duplicate does in 6.1.
- **Indices continue**: round 2's tasks get the next indices after round 1's, so `item` tags and `map_results` keys stay unique and resume works unchanged.
- **Output**: only completed tasks, in plan order across rounds; `data` gains `rounds` (number of plans made) and lists every task with its `round` and status. `writers` lists completed writer tasks only, so a gate after shows only those.
- **End**: the orchestrator completes when the last round's tasks all complete. It fails when a task fails and no rounds are left (``task 'b' failed after 2 replans: …``), or a replan turn fails or is off-schema.
- **Limits**: each replan turn counts as one agent spawned when it starts; a round's tasks count on `agents_spawned` when it is planned (over it: `policy_limit_exceeded`, a clean stop). As in 6.1, validation counts only the hub (workers are counted at run time). In the last round a failure cancels the others, as in 6.1: waiting for them would only add cost. Wall time and budget stop a run mid-replan as anywhere else.
- **Resume**: rounds are checkpointed in `RunState.plans` (each task carries its `round`) and counted in a new `RunState.rounds` (an empty replan still counts), so a resumed run never asks the hub again for a round it has and runs only tasks that had not ended.
- **Events**: `plan_made` gains `round` (1 for the first); a new `replan_started` (`round`, `failed: [{id, error}]`, `dropped: [ids]`) before the replan turn; `task_completed` may carry `status: "dropped"`; `node_completed` gains `rounds`.
- **Contract** in tech-stack ("Orchestrator (API contract)", updated) and decisions-log rows; `schemas/` export; the manifest's `parameters` gain `replan` (the side panel shows it with no web change); regenerated fixtures and API types.

### Out of scope
- Replan on other triggers (low confidence, the hub's own review of results, `always`): only `on: "failure"`.
- Retrying a task as-is without the hub, or backoff between rounds.
- A console view of rounds, dropped tasks or the replan reason beyond the step list's existing rows (6.4).
- Merging writer branches or publishing them (6.3).
- Nested orchestrators (still refused, as 6.1).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| What happens on failure | Settle, then replan: running tasks finish, unstarted tasks are dropped, then the hub replans | User's choice. No in-flight work is thrown away, and the hub replans once with every outcome of the round rather than once per failure. |
| Spec shape | `replan: {on: "failure", max_rounds}` (1..3), unset = off | An object leaves room for other triggers without a breaking change; a low cap keeps cost bounded (mission 2). Off by default keeps 6.1 specs unchanged. |
| What the hub sees | The original input plus every task's id, title, status, output or error, as JSON input; instructions unchanged plus a fixed replan paragraph | Mission 5: a worker's error text can come from repo content, so it is data. |
| Task ids across rounds | Unique across all rounds | A writer's key and branch are the task id; reuse would put a new attempt on a failed attempt's branch. |
| Plan size on replan | At most `max_workers` minus completed tasks | `max_workers` stays the most work an orchestrator does; replans cannot grow it. |
| State | Rounds appended to the same `plans` list and `map_results` indices, plus `RunState.rounds` | Resume, `item` tags and reduce sources work as in 6.1; the count is needed because a replan may plan no task. |

## Open questions
- None. (The roadmap's "Next up" line still names Milestone 4 at 4.8, done in #156; it should name Milestone 6, in its own PR with a changelog entry.)
