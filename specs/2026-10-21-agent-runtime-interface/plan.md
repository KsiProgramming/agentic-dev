# Plan: AgentRuntime interface + fake runtime

Order: contract first, then the fake runtime, then the engine helper, then the docs. CI stays green after each group.

## 1. Runtime contract
- [ ] `packages/runtime/pyproject.toml`: add the `pydantic>=2.11` dependency, then run `uv lock`.
- [ ] `packages/runtime/src/agentic_runtime/events.py`:
  - `TextDelta`, `Message`, `ToolCall`, `ToolResult`, `Usage`, `Completed`, `Failed`, `Cancelled`.
  - `AgentEvent = Annotated[Union[...], Field(discriminator="type")]`.
  - `TERMINAL_EVENT_TYPES`.
- [ ] `packages/runtime/src/agentic_runtime/request.py`: `AgentRequest` (frozen, `extra="forbid"`).
- [ ] `packages/runtime/src/agentic_runtime/protocol.py`:
  - `AgentRun` Protocol: `__aiter__`, `cancel()`.
  - `AgentRuntime` Protocol: `start(request) -> AgentRun`.
  - Docstrings state the contract rules: exactly one terminal event, nothing after it, `tool_result` matches an earlier `tool_call`, `usage` before `completed`.
- [ ] `agentic_runtime/__init__.py`: re-export the public names.
- [ ] `packages/runtime/tests/test_events.py`:
  - Each event round-trips through JSON.
  - The discriminator rejects an unknown `type`.
  - Extra keys are rejected.
- [ ] Remove `packages/runtime/tests/test_import.py`; it is superseded.

## 2. Fake runtime + cancellation
- [ ] `packages/runtime/src/agentic_runtime/fake.py`:
  - `FakeRuntime(scripts: Mapping[str, Script] | None = None)`.
  - `Script` is a sequence of steps: an event, or `Delay(seconds)`.
  - The default echo script is `message(input)` → `usage` → `completed`.
  - `FakeRuntime.requests` records the requests it received.
  - `FakeRun` implements `AgentRun` with cooperative cancel through an `asyncio.Event`, which is checked between steps and races each delay.
  - The fake appends a `completed` event if a script has no terminal event. It raises if a script breaks the contract, for example a `tool_result` without a matching `tool_call`, or events after a terminal one.
- [ ] `packages/runtime/tests/conftest.py`: an autouse no-network fixture that patches `socket.socket.connect` and `socket.create_connection` to raise.
- [ ] `packages/runtime/tests/test_fake_runtime.py`:
  - Echo default.
  - Scripted per `node_id`.
  - Tool call then tool result.
  - Scripted failure gives `failed`.
  - Exactly one terminal event, always last.
  - Requests are recorded.
  - Invalid scripts are rejected.
  - Cancel cases: cancel before iteration gives only `cancelled`; cancel during a `Delay` gives `cancelled` promptly; cancel after `completed` is a no-op; a double cancel is idempotent.
  - The no-network guard itself works: a `socket.create_connection` attempt raises.

## 3. Engine helper
- [ ] `packages/engine/pyproject.toml`: add the `agentic-runtime` workspace dependency, then run `uv lock`.
- [ ] `packages/engine/src/agentic_engine/agent.py`:
  - `to_request(node, input) -> AgentRequest`.
  - `AgentNodeResult` holds `status`, `text`, `usage`, `tool_calls`, `events` and `error`.
  - `async run_agent_node(node, runtime, input) -> AgentNodeResult`.
  - `failed` and `cancelled` are returned as statuses, not raised.
- [ ] `packages/engine/tests/conftest.py`: the same no-network fixture. Share it through a small `agentic_runtime.testing` module so it is not duplicated.
- [ ] `packages/engine/tests/test_agent_node.py`:
  - **Done when**: parse a sample spec (fixture from 0.2), take its agent node, run it on `FakeRuntime`, and assert the text, usage and `completed` status.
  - Tool-call script surfaces in `tool_calls`.
  - Failure maps to the `failed` status.
  - The request maps `role`, `instructions`, `model` and `tools` from the node.

## 4. Docs
- [ ] README: add a short "Agent runtime" section covering the contract, the event list and how to script `FakeRuntime` in tests.
- [ ] CHANGELOG: add a 0.3 entry.
