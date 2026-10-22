# Plan: `gate` primitive (LangGraph interrupt) + `POST /runs/{id}/approvals`

Built engine first. Each group leaves the project working and CI green.

## 1. Spec: `GateNode`
- [ ] `packages/engine/src/agentic_engine/spec/models.py`:
  - Add `GateNode` (`type: "gate"`, `id`, `title: NonEmptyStr`, `prompt: str | None`) to the `Node` union.
  - `node_tools` returns `[]` for it.
- [ ] Re-export the JSON Schema (same command as 0.2), and commit the updated schema file.
- [ ] Fixtures:
  - `valid/gate-approval.json` (writer agent → gate → `repo.list_files` tool node).
  - `invalid/gate-missing-title.json`.
- [ ] `test_spec.py`: the gate round-trips, and the invalid gate fixture is rejected.

## 2. Engine: interrupt, waiting and continuing
- [ ] `events.py`:
  - Add `GATE_WAITING` and `GATE_DECIDED`.
  - Add `"waiting"` to `RunStatus`.
  - Map `gate_waiting` to the `waiting` status where the run status is derived from events.
- [ ] `agentic_engine/gate.py`:
  - `GateDecision` (Pydantic): `decision: Literal["approve", "reject"]`, `comment: str | None`, `decided_by: str | None`.
  - `run_gate_node(node, input, log)`:
    - Its first statement is `interrupt({...})`.
    - After resume it validates the value as a `GateDecision` and emits `gate_decided`.
    - It returns `AgentNodeResult(status="completed", text=input)` on approve.
    - It returns `AgentNodeResult(status="cancelled", text=input, error="rejected at gate: …")` on reject.
- [ ] `graph/compile.py`: `step_nodes` accepts `GateNode`. `_step` sends gates to `run_gate_node`, keeps the `NODE_END` emission, and emits no `node_started` for gates, because `run.py` does that. Update the module docstring.
- [ ] `graph/run.py`:
  - After `ainvoke`, check `aget_state(config).interrupts`.
  - If the run paused, emit `node_started` and `gate_waiting` (`title`, `prompt`, `artifact`) for the pending gate, and return `WorkflowRunResult(status="waiting", waiting_at=<gate id>)`.
  - `resume_workflow` takes an optional `decision: GateDecision`. On a run paused at a gate it emits `run_resumed` and invokes `Command(resume=decision.model_dump())`. (A separate `continue_workflow` was planned; one optional parameter turned out to be enough.)
  - `resume_workflow` on a paused run with no decision (a worker died right after the pause) runs the gate again, which pauses again and announces the pause again. This is the same as a cut-off node running again in 1.3, and it keeps the run status right.
- [ ] `graph/state.py`: add `"waiting"` to `WorkflowRunResult.status` and a `waiting_at: str | None` field.
- [ ] Tests in `packages/engine/tests/test_gate.py` (fake runtime, `InMemorySaver`):
  - A run stops at the gate with events `… node_started(gate), gate_waiting`, status `waiting`, and the next node not run.
  - Approve: `gate_decided`, `node_completed(gate)`, the next node gets the pre-gate text, and the run ends `run_completed`.
  - Reject: `node_cancelled(gate)`, the run ends `run_cancelled` with `stopped_at=gate`, and the next node never runs.
  - `seq` has no gaps across the pause and the continue, and no event is duplicated.
  - Resuming without a decision stays `waiting`.
  - A spec with two gates pauses twice.

## 3. Store: `waiting` status and the `approvals` table
- [ ] Alembic `0009_approvals.py`:
  - Create the `approvals` table (`id`, `run_id` FK, `node_id`, `decision` with a check constraint, `comment`, `decided_by` nullable, `created_at`), unique on `(run_id, node_id)`.
  - Add a downgrade.
- [ ] `agentic_store/models.py`: add an `Approval` model, and document `waiting` in the `Run` docstring.
- [ ] `agentic_store/sink.py` (or wherever the status is updated from events): set `waiting` on `gate_waiting`.
- [ ] `agentic_store/approvals.py`:
  - `record_approval(sessions, run_id, node_id, decision, comment)`:
    - In one transaction it locks the run (`FOR UPDATE`), checks that it is `waiting` at `node_id`, inserts the approval and sets `status="queued"`.
    - It raises `RunNotWaiting`, `WrongGate` or `AlreadyDecided`.
    - The pending gate is the `node_id` of the run's last `gate_waiting` event with no approval yet.
  - `pending_decision(sessions, run_id)` returns `GateDecision | None`.
- [ ] Export both from `agentic_store/__init__.py`. `lease.LIVE_STATUSES` stays `("queued", "running")`. Write a comment saying why `waiting` is not in it.

## 4. API: `POST /runs/{id}/approvals`
- [ ] `agentic_api/runs/models.py`: `ApprovalRequest` (`node_id`, `decision`, `comment?`) and `ApprovalResponse` (`run_id`, `node_id`, `decision`, `status`).
- [ ] `agentic_api/runs/routes.py`:
  - Add the endpoint, which calls `record_approval` and then `enqueue_run`.
  - Map the errors: `RunNotWaiting`, `WrongGate` and `AlreadyDecided` give `409`, and an unknown run gives `404` (`existing_run`).
  - It returns `202`.
- [ ] Regenerate the OpenAPI spec and the web API client, so the frontend client stays in sync.

## 5. Sandbox kept across the pause
- [ ] `agentic_sandbox/protocol.py`: `SandboxManager.open(run_id, repo, *, reuse: bool = False)` yields `(sandbox, reused: bool)` or a sandbox with a `reused` flag. Add `keep()` on the context (or a `KeepSandbox` signal) so that leaving it does not destroy the sandbox. Document the lifecycle.
- [ ] `docker_backend.py`:
  - With `reuse`, attach to the running container and volume labelled for the run (start the container if it stopped) and skip the clone.
  - Without it, keep today's "remove leftovers, create fresh" behaviour.
  - When kept, the `finally` block skips `_remove`.
- [ ] `fake.py`: the same behaviour, keeping the temp dir by run id.
- [ ] `worktree.py` / `RepoTools`: if `/workspace/worktrees/<node-id>` already exists on branch `agent/<run>/<node>`, reuse it instead of `worktree add -b`.
- [ ] Tests: the fake sandbox `keep` → `open(reuse=True)` returns the same files and worktree. A Docker test does the same, behind the existing Docker marker.

## 6. Worker: pause, then continue
- [ ] `agentic_worker/main.py`:
  - `_workflow` calls `resume_workflow(…, decision=…)` when `pending_decision(run)` is set, `resume_workflow` when `attempt > 1`, and `run_workflow` otherwise.
  - A `waiting` result keeps the sandbox, and `process_run` releases the lease as for an ended run. Set `lease_expires_at` to NULL, so the expired-lease reclaim never picks the run up.
  - The run is opened with `reuse=True` whenever a sandbox for it may exist (`attempt > 1` or a pending decision).
- [ ] `build_sandboxes`: the startup sweep's `keep` set adds the ids of `waiting` runs.
- [ ] Docs:
  - README "Gates" section: the spec shape, the event sequence, the curl example to approve or reject, and the `waiting` status.
  - CHANGELOG entry.
  - Tick this plan.
