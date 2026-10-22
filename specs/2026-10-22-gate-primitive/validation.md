# Validation: `gate` primitive (LangGraph interrupt) + `POST /runs/{id}/approvals`

## Done when (from roadmap)
> A run pauses at a gate and resumes on approval

## Automated checks
User choice: engine unit tests are the required new tests for this phase. They run on the fake runtime with LangGraph's `InMemorySaver`, with no network and no database.

- [ ] `test_spec.py`:
  - `valid/gate-approval.json` validates.
  - `invalid/gate-missing-title.json` is rejected.
  - The exported JSON Schema contains `gate`.
- [ ] `test_gate.py`, pause:
  - A run with `agent → gate → tool` returns status `waiting` with `waiting_at="gate"`.
  - The events end with `node_started(gate)` and `gate_waiting`.
  - The `gate_waiting` payload has `title`, `prompt` and `artifact` (the agent's output).
  - The tool node has not run.
- [ ] `test_gate.py`, approve:
  - `resume_workflow(decision=approve)` emits `run_resumed`, `gate_decided`, `node_completed(gate)`, the tool node's events and `run_completed`.
  - The tool node received the pre-gate text.
- [ ] `test_gate.py`, reject:
  - `resume_workflow(decision=reject)` and a comment emits `gate_decided` and `node_cancelled(gate)`, then `run_cancelled` with `stopped_at="gate"`.
  - The tool node never runs.
- [ ] `test_gate.py`, no duplicates: across the pause and the continue, `seq` is 1..n with no gaps. `node_started(gate)` and `gate_waiting` each appear exactly once.
- [ ] `test_gate.py`, resume without a decision: `resume_workflow` on a paused run with no decision returns `waiting` again, announces the pause again (`run_resumed`, `node_started`, `gate_waiting`) and runs nothing else. A later approval still completes the run.
- [ ] `test_gate.py`, two gates: a spec with two gates pauses twice and completes after two approvals.
- [ ] The existing engine, store, API, worker and sandbox suites still pass. No existing test is changed to fit, except where the `Node` union or the status literals widened.
- [ ] `ruff check`, `ruff format --check`, and strict `pyright`/`mypy` are clean across the workspace.
- [ ] Alembic: the existing `test_migrations.py` upgrade/downgrade round-trip passes with `0009_approvals`.

## Manual / demo checks
This is the "Done when" demo with `docker compose up --build` and the fake runtime (`AGENT_RUNTIME=fake`, as in earlier demos).

- [ ] Start a gated run:
  `curl -s -X POST localhost:8000/runs -H 'content-type: application/json' -d @packages/engine/tests/fixtures/specs/valid/gate-approval.json` (wrapped in the usual `{spec, input, repo}` body). It returns `202` with a run id.
- [ ] `curl -N localhost:8000/runs/<id>/events`: the stream shows the writer's commit, then `node_started(gate)` and `gate_waiting`, and then stays quiet. The run status is `waiting`. `docker ps --filter label=agentic.run_id=<id>` still lists the sandbox. The worker is free: a second run started meanwhile completes.
- [ ] Approve: `curl -s -X POST localhost:8000/runs/<id>/approvals -d '{"node_id":"gate","decision":"approve"}' -H 'content-type: application/json'` returns `202`. The SSE stream continues with `run_resumed`, `gate_decided`, `node_completed`, and the tool node listing a tree that includes the file written before the gate, followed by `run_completed`.
- [ ] Repeat the approval: it returns `409`. Approving a run that is not waiting, or naming the wrong node, also returns `409`.
- [ ] Reject path: on a new run, `decision: "reject"` ends the run `cancelled` with `stopped_at: "gate"`, and the sandbox is removed.
- [ ] Restart while waiting: `docker compose restart worker` during the pause leaves the sandbox in place (the startup sweep keeps it). Approving afterwards still completes the run.
- [ ] The monitor page for the run lists `gate_waiting` and later `gate_decided`.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The manual demo steps were run once, and the result is noted in the PR description.
- [ ] README "Gates" section and CHANGELOG are updated, the OpenAPI spec and web client are regenerated, and the JSON Schema is re-exported.
- [ ] No secrets in logs or event payloads (the existing no-leak test still passes).
- [ ] The roadmap phase 1.7 is marked done in the PR (`complete-phase`).
