# `gate` primitive (LangGraph interrupt) + `POST /runs/{id}/approvals`

Roadmap phase: 1.7
Branch: plan/1.7-gate-primitive

## Context
After 1.6, a writer node can commit to `agent/<run>/<node>` inside the run's sandbox. Nothing irreversible happens yet. A run always goes straight to its end, and no human can stop it partway. This phase adds the `gate` primitive. A run pauses at a gate, waits for a human decision without holding a worker, and then resumes or stops.

It depends on these phases, all done:
- 0.2/0.4: the spec union and the compiler.
- 0.5/0.6: the run event log and the runs API with SSE.
- 1.3: the Postgres checkpointer, leases and resume. A gate is a planned resume.
- 1.1/1.6: the per-run sandbox and writer worktrees, which must survive the pause.

It unblocks:
- 1.8: `github.openPR` behind a gate. It pushes the branch that a writer committed before the gate, so that branch must still exist after approval.
- 1.11/1.12: the docs template and repo creation, both gated.
- 2.6: approval cards in the monitor, built on this endpoint and the `approvals` table.
- 2.7: the audit log, which reads `approvals`.
- 8.7: Autonomous mode, which still stops at write gates.

Principles that apply:
- **Humans approve irreversible actions (3):** this is the mechanism behind that rule. Phase 1.7 delivers the primitive. Enforcing "every push/PR has a gate" is the validation work of 1.8 and 2.4.
- **One spec, many views (1):** a gate is an ordinary spec node, so the canvas, the Architect and the monitor treat it like any other node.
- **Transparency (6):** the pause and the decision are both in the append-only `run_events` stream. Each decision is also a row in `approvals`.
- **Repo content is data (5):** the text shown at the gate is the previous node's output. It is shown as data, and the human decides.
- **Small, verifiable steps (7):** approve and reject only. No edits, timeouts or UI.

Tech-stack choices that apply: LangGraph `interrupt()` for `gate`, with `Command(resume=...)` on the same thread. The Postgres checkpointer keeps the paused state. The run queue (Redis) and leases bring the run back to a worker.

## Scope
### In scope
- **Spec:**
  - `GateNode` is `{"type": "gate", "id", "title", "prompt"?}` and joins the `Node` union.
  - The JSON Schema is re-exported, and valid and invalid fixtures are added.
  - A gate passes its input through unchanged: the next node gets the output of the node before the gate.
- **Engine:**
  - A gate compiles to a LangGraph node whose first statement is `interrupt(...)`. LangGraph runs the node again from its start on resume, so nothing is emitted before that line.
  - When the graph stops at an interrupt, `run_workflow` and `resume_workflow` emit `node_started` and `gate_waiting` and return a `WorkflowRunResult` with status `waiting`. The `gate_waiting` payload has `title`, `prompt` and the gate's input text as `artifact`.
  - A new `continue_workflow(…, decision)` resumes the graph with `Command(resume=decision)`.
  - The gate node then emits `gate_decided` (`decision`, `comment`, `decided_by`).
  - On approve it emits `node_completed`, and the run continues.
  - On reject it emits `node_cancelled`, and the run ends `cancelled` with `stopped_at=<gate id>`.
- **Run status `waiting`:** it is set when `gate_waiting` is written. It is not a live status for leases, so no worker reclaims a waiting run.
- **`approvals` table** (Alembic migration):
  - Columns: `id`, `run_id`, `node_id`, `decision` (`approve` or `reject`), `comment`, `decided_by` (nullable until auth exists), `created_at`.
  - It is unique on `(run_id, node_id)` for now. Gates inside `loop` and `map` (1.9/1.10) will need an iteration key later.
- **`POST /runs/{id}/approvals`** with body `{node_id, decision, comment?}`:
  - In one transaction, it checks that the run is `waiting` at that gate, inserts the approval, sets the run back to `queued` and then enqueues it.
  - It returns `404` for an unknown run.
  - It returns `409` when the run is not waiting, when the node is not the gate it waits at, or when the gate was already decided.
  - It returns `422` for a bad decision value.
- **Worker:**
  - When a run ends `waiting`, the worker releases its lease and keeps the sandbox.
  - It claims a re-queued run through the existing claim path. If the run has a recorded decision for its pending gate, the worker calls `continue_workflow`.
- **Sandbox kept across the pause:**
  - The `SandboxManager` gets `keep`/`attach` behaviour. On a pause, the container and volume (labelled `agentic.run_id`) are left running, and resuming reattaches to them. If they are gone, a fresh sandbox is created and the 1.3 rule applies.
  - `RepoTools` reuses a writer's existing worktree and branch instead of failing on `worktree add -b`.
  - The worker's startup sweep keeps the sandboxes of `waiting` runs, not only those of leased runs.
- **Demo fixture** `gate-approval.json`: a writer agent, then a gate, then a `tool` node running `repo.list_files`.
- **Docs:** a README section on gates covers the spec shape, the `waiting` status, the approvals endpoint with a curl example, and what reject does.

### Out of scope
- Editing the artifact at the gate before approving: 2.6.
- Approval cards or an approve button in the monitor: 2.6. The existing event list already shows the gate events.
- Gate timeouts and auto-reject: 2.2 (wall time) or later.
- Who may approve (roles and auth). `decided_by` stays nullable until auth lands.
- Validation that every push, PR or repo creation sits behind a gate: 1.8 and 2.4.
- Gates inside `loop`, `map` or `parallel`: 1.9/1.10/3.1, which add an iteration or branch key to the approval.
- Cancelling a waiting run through the API.
- Reaping sandboxes of runs left waiting for a long time (a TTL sweep). This is noted for 2.2/9.2.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Approve + reject, with an `approvals` table | User choice. Reject is the other half of a human decision, and the table is what 2.6/2.7 build on. |
| Reject outcome | Run ends `cancelled`, `stopped_at=<gate>`, gate gets `node_cancelled` | It reuses the existing run end statuses and `stopped_at`. A rejection is a stop, not an error. |
| Worker during the pause | Release the lease; a re-enqueued run is claimed by any worker | User choice. An open gate can wait hours, and it must not tie up a worker slot. It reuses the claim and resume path from 1.3. |
| Sandbox during the pause | Keep it, reattach on resume, recreate only if gone | User choice. 1.8 must push the branch committed before the gate. Recreating the sandbox would lose it. |
| Where gate events are emitted | `run.py` emits `node_started` + `gate_waiting` when the graph stops interrupted. The gate node emits `gate_decided` + its end event after resume. | LangGraph runs an interrupted node again from its start. Events emitted before `interrupt()` would be duplicated. |
| Resume value | `{"decision", "comment", "decided_by"}`, read by the worker from `approvals` | The table is the source of truth. The queue only carries the run id, as before (`agentic_store.queue`). |
| New status | `waiting`, not in `LIVE_STATUSES` | A waiting run has no lease and must never be reclaimed as abandoned. |
| Approval uniqueness | `(run_id, node_id)` | A gate is decided at most once per run until loops and maps exist. A double submit gets `409`. |

## Open questions
- Can a stopped container survive a host reboot? For local dev, a lost sandbox falls back to recreation, and the writer's commits are gone. Is that acceptable until 1.8, or must 1.8 push the branch before the gate? Decide in 1.8.
