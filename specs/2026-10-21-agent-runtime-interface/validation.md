# Validation: AgentRuntime interface + fake runtime

## Done when (from roadmap)
> Engine tests can run an agent node with no network

## Automated checks
- [ ] `packages/engine/tests/test_agent_node.py::test_runs_agent_node_from_spec_on_fake_runtime`: an `AgentNode` from a parsed sample spec runs through `run_agent_node` on `FakeRuntime`. It returns status `completed`, the expected text and a usage with token counts.
- [ ] No-network guard is active (autouse) in `packages/runtime/tests` and `packages/engine/tests`. A test proves that an outbound `socket.create_connection` raises inside those suites.
- [ ] `test_events.py`:
  - Every `AgentEvent` type round-trips through JSON.
  - An unknown `type` is rejected.
  - Extra keys are rejected.
- [ ] `test_fake_runtime.py` contract cases:
  - Exactly one terminal event, and it is last.
  - `usage` comes before `completed`.
  - Every `tool_result` follows a `tool_call` with the same `call_id`.
  - Invalid scripts are rejected.
- [ ] `test_fake_runtime.py` cancellation cases:
  - Cancel before iteration yields only `cancelled`.
  - Cancel during a delay yields `cancelled` within 100 ms.
  - Cancel after `completed` is a no-op.
  - A double cancel is idempotent.
- [ ] `test_agent_node.py`:
  - Tool calls surface in the result.
  - `failed` and `cancelled` map to statuses without raising.
  - Request mapping from `AgentNode` is correct.
- [ ] `pyright` (strict) passes, and `FakeRuntime` is accepted where an `AgentRuntime` is expected (no casts or `# type: ignore`).
- [ ] Existing CI jobs are green:
  - `ruff check`
  - `ruff format --check`
  - `pytest`
  - schema freshness
  - web
  - API contract

## Manual / demo checks
- [ ] Run `uv run pytest packages/runtime packages/engine -v` with networking disabled, or offline. Expected: all tests pass.
- [ ] Run `uv run python -c "import agentic_runtime, sys; print('agentic_engine' in sys.modules)"`. Expected: `False`, because the runtime does not import the engine.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The scope matches `requirements.md`:
  - No LangGraph.
  - No real provider.
  - No tool execution, only replay.
- [ ] README and CHANGELOG are updated.
- [ ] Roadmap phase 0.3 is marked done in the PR (`complete-phase` skill or the CI check).
