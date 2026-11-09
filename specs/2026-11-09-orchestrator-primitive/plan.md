# Plan: `orchestrator` primitive

Contract first: the spec model, plan schema, validation and the written contract land before any runtime code, and the engine suite stays green after each group.

## 1. Contract: spec model, plan schema, validation, policy
- [ ] `agentic_engine/spec/models.py`: `OrchestratorHub` (`role`, `instructions`, `provider?`, `model?`, as `ReduceAgent`) and `OrchestratorNode` (`hub`, `body`, `max_workers` 1..`MAX_AGENTS_SPAWNED`, `max_concurrency` 1..`MAX_AGENTS_ALIVE`, `writes?`); add it to the `Node` union, `iter_nodes`, `node_tools`, `agents_spawned` (hub + `max_workers` × the body's agents, worst case).
- [ ] `orchestrator_plan_schema(node)` (beside `classifier_schema`): `{tasks: [{id, title ≤ 80, instructions ≤ 4000}] maxItems max_workers, reason ≤ 300}`, task `id` a slug pattern; check that `<orchestrator>--<task>` fits `NodeId` and the branch name rules (else switch the separator, see requirements' open question).
- [ ] Structure rules in `spec/validate.py`: `not_allowed_in_orchestrator` for a gate, publisher, repo creation, map, parallel, loop, router or orchestrator in `body`, and for an orchestrator inside a map, parallel, loop body or another orchestrator; `reference` for a publisher whose `from_node` is the orchestrator or inside it; `reduce.from` may name an orchestrator; `writes` rules as for a map (no `writes` inside `body`).
- [ ] Policy in `models.py`'s limit check: `max_concurrency` against `agents_alive`, the orchestrator as one `max_depth` level.
- [ ] Add the issue code to the codes list; `scripts/export_workflow_schema.py` → `schemas/workflow-spec` JSON Schema.
- [ ] `specs/tech-stack.md`: new "Orchestrator (API contract)" section (spec, plan, workers, writers, events, resume, limits, validation) and decisions-log rows from requirements; `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] Tests: model accepts a sample spec and refuses each forbidden body; validation issue paths and codes; `agents_spawned` worst case.

## 2. Runtime: hub, plan, workers, resume, events
- [ ] `graph/state.py`: `RunState.plans` (orchestrator id → tasks, merged; checkpoints without it read as empty).
- [ ] `graph/compile.py`: at the top of a run, the orchestrator compiles to an entry node that runs the hub turn (role `hub`, typed by the plan schema, waiting for an `agents_alive` slot) and records the plan, one `Send` per task to a worker node that runs `body` through `_run_inline` with input `{task, input}`, and `<id>.done` that joins in task order. A resumed run with a plan skips the hub.
- [ ] Limits at plan time: count the hub and each task's agents on `agents_spawned` (`policy_limit_exceeded` with `limit: "agents_spawned"` when over); workers take `agents_alive` slots; at most `max_concurrency` tasks at once.
- [ ] Failure: a failed worker cancels the others (`node_cancelled`) and fails the orchestrator with the task named (``worker 't2' of 'fix' failed: …``); empty plan completes with `[]`.
- [ ] Events (`events.py`): `plan_made {tasks: [{id, title}], reason}`, `task` tag on worker events, `node_completed {tasks, completed}`; hub usage is the orchestrator's (budget metering unchanged).
- [ ] Output: list in task order as the result; `reduce` sources by task id; `writes` stores it.
- [ ] Tests on the fake runtime (scripts keyed by node id and task): see validation.md.

## 3. Writer workers
- [ ] `agentic_sandbox/worktree.py`: `add_worktree` for a dynamic writer key; `branch_name` for `<orchestrator>--<task>`.
- [ ] `agentic_tools/repo/routing.py`: writers can be added while the run runs; a call's writer key comes from the node id and the task tag in the tool context (`RunTools.call(..., node_id=…, task=…)` or a composed key passed by the runtime request).
- [ ] Engine: before a writer task starts, ask the run's executor for its worktree (an `ensure_writer` hook on the tools, a no-op without a sandbox); record the writer keys in `RunState` so gate review and resume see them.
- [ ] `agentic_engine/gate.py` / worker `SandboxGateReview`: the writers a gate shows are the static ones plus the plan's writer keys that completed before it.
- [ ] Worker (`agentic_worker/main.py`): pass the dynamic-writer hook into `open_repo_tools`; `writer_node_ids` stays the static set.
- [ ] Tests: a worker writes a file on `agent/<run>/fix--t1` (fake sandbox), a gate after the orchestrator lists both tasks' changes, edits commit on the right branch, `openPR` from it is a `reference` issue.

## 4. Manifest, fixtures and a sample
- [ ] `agentic_engine/nodes.py`: manifest (`label` "Orchestrator", `category` `flow`, icon `network`, `slots: ["body"]`, a `default` with a hub and one agent worker, `ui` for `hub.instructions` as textarea).
- [ ] Regenerate `schemas/fixtures/node-types.json` (and port-check fixtures if the orchestrator's output type touches them); run the web's unit tests to confirm the palette and ops mirrors accept the new kind.
- [ ] A sample spec in `schemas/examples/` (or the engine tests' fixtures): hub splits "document each package" into N tasks, an agent worker per task, a `concat` reduce after it.
- [ ] `docs/architecture/` mentions of the orchestrator as "planned" updated to what 6.1 ships.
