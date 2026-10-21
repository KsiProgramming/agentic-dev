# AgentRuntime interface + fake runtime

Roadmap phase: 0.3
Branch: plan/0.3-agent-runtime-interface

## Context
The tech stack defines one `AgentRuntime` interface ("start → async iterator of `AgentEvent`, plus cancel") with Claude and Copilot adapters behind it. It also calls for "a fake `AgentRuntime`" that gives deterministic engine tests. This phase defines that contract and the fake runtime. No real provider is called yet.

It depends on 0.1 (the `agentic-runtime` package exists but is empty) and 0.2 (`AgentNode` in `agentic_engine.spec`). Both are done. It unblocks:
- 0.4: compiling a `sequence` of `agent` nodes to LangGraph runs each node through this interface, on the fake runtime.
- 0.5: the engine turns `AgentEvent`s into `run_events` rows.
- 0.7: the Claude adapter implements this interface.
- 2.1: cost per node comes from the normalised usage event defined here.
- 1.2/1.6: the tool-call and tool-result events are shaped here, before the `repo` MCP tools exist.

Principles that apply:
- **Tools live in the platform (4)**: tool-call events describe calls to platform-owned tools in a provider-neutral way. Adapters translate their SDK's events into them.
- **Transparency (6)**: every agent action becomes an event the engine can log.
- **Repo content is data (5)**: input text and tool results are carried as data fields. They are never merged into the instructions.

## Scope
### In scope
- `agentic_runtime` contract, as Pydantic v2 models plus a `typing.Protocol`:
  - `AgentRequest`: `node_id`, `role`, `instructions`, `input` (text), optional `model`, `tools: list[str]`. The runtime does **not** import `agentic_engine.spec`.
  - `AgentEvent`, a discriminated union on `type`:
    - `text_delta`: a streamed chunk.
    - `message`: the final assistant text.
    - `tool_call`: `call_id`, `name`, `arguments`.
    - `tool_result`: `call_id`, `output`, `is_error`.
    - `usage`: `input_tokens`, `output_tokens`, optional `premium_requests`, optional `estimated_usd`.
    - `completed`: terminal.
    - `failed`: terminal, with `error` and `retryable`.
    - `cancelled`: terminal.
  - `AgentRuntime` Protocol: `start(request) -> AgentRun`. An `AgentRun` is an async iterator of `AgentEvent` and has `cancel() -> None`.
  - Contract rules, written in the docstrings and enforced by the fake runtime's tests:
    - Every stream ends with exactly one terminal event (`completed` | `failed` | `cancelled`).
    - Nothing comes after the terminal event.
    - Every `tool_result` follows a `tool_call` with the same `call_id`.
    - `usage` is emitted at least once before `completed`.
- Cancellation semantics:
  - `cancel()` is idempotent and safe to call before, during or after iteration.
  - After `cancel()`, the stream yields `cancelled` (unless it already ended) and stops.
  - Cancelling a run that has finished is a no-op.
- `FakeRuntime` in `agentic_runtime.fake`:
  - Scripted per `node_id` with a list of events or steps, including tool calls and their results, failures and per-step delays for cancel tests.
  - The default script echoes the input as a `message` and adds a fixed `usage` event.
  - It records the requests it received, for assertions.
  - It uses no network or I/O.
- Engine helper `agentic_engine.agent.run_agent_node(node: AgentNode, runtime: AgentRuntime, input: str) -> AgentNodeResult`:
  - Maps the node to an `AgentRequest`.
  - Collects the events.
  - Returns the final text, the usage, the tool calls and the terminal status.
  - This is the seam that 0.4 wraps in a LangGraph node.
- A no-network guard for the runtime and engine test suites.

### Out of scope
- The LangGraph compile/sequence of nodes (0.4).
- Persisting events in `run_events` (0.5).
- The Claude adapter and real HTTP (0.7). The Copilot adapter is 7.2.
- Executing tools: the fake only *replays* scripted tool calls and results. Real MCP tools come in 1.2 and 1.6.
- Structured output and capability-gap validation (7.3).
- Converting usage into USD (2.1). `estimated_usd` is only carried through.
- Policy limits and budget (2.2–2.3).
- A reusable conformance suite for every adapter. It is not chosen for now and can be added in 0.7 if it is useful.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Event modelling | Pydantic v2 discriminated union on `type`, frozen, `extra="forbid"` | Same pattern as the workflow spec (0.2). Events must serialise cleanly into `run_events` (0.5) and SSE (0.6). |
| Interface style | `typing.Protocol` (structural) + `AgentRun` handle with `__aiter__`/`cancel()` | Matches the tech stack's "start → async iterator, plus cancel". Under pyright strict, adapters need no base class. |
| Dependency direction | `agentic-runtime` does not depend on `agentic-engine`; the engine maps `AgentNode` → `AgentRequest` | The runtime stays provider-facing and reusable. This avoids an import cycle when the engine depends on the runtime. |
| Terminal events | Exactly one of `completed` / `failed` / `cancelled` | Consumers (engine, monitor) get one unambiguous end state per node. |
| Tool events now | `tool_call` + `tool_result`, replayed by the fake runtime only | User chose the broader scope. This fixes the event shape before 1.2 so the monitor and engine do not change later. |
| Cancel model | Cooperative: sets a flag/event that the stream checks between events and during delays; idempotent | Simple and deterministic in tests. Real adapters will also cancel their underlying SDK call (0.7). |
| No-network guard | conftest fixture patching `socket.socket.connect` (autouse in runtime + engine tests) | "Done when" says *no network*. The guard enforces this without a new dependency. |

## Open questions
- None
