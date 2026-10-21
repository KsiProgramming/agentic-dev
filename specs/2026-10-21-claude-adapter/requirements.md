# Claude adapter (API key from env for now)

Roadmap phase: 0.7
Branch: plan/0.7-claude-adapter

## Context
Phases 0.1–0.6 give us a walking skeleton that only runs on `FakeRuntime`. This phase adds the first real provider: a `ClaudeRuntime` that implements the `AgentRuntime` protocol from 0.3 (`agentic_runtime.protocol`). With it, a run started with `POST /runs` reaches Claude and streams real events over SSE. The API key comes from the environment for now. Encrypted per-workspace secrets come in 1.4.

It depends on 0.3 (the contract and `check_events`), 0.4/0.5 (the engine runs agent nodes and logs their events) and 0.6 (the worker and the SSE stream). All are done. It unblocks:
- 0.8: the monitor page shows real `text_delta` events.
- 1.2: the `repo` MCP tools plug into the tool loop skeleton added here.
- 2.1: cost per node is computed from the `usage` events emitted here.

Tech-stack choice: the tech stack allows "Claude Agent SDK (Python), or our own tool loop on the Anthropic Messages API". We pick **our own loop on the Messages API** with the official `anthropic` Python SDK (`AsyncAnthropic`, `messages.stream`).

Principles that apply:
- **Tools live in the platform (4).** The loop only routes Claude's `tool_use` blocks to a platform-owned executor. Claude never gets its own built-in tools.
- **Repo content is data (5).** `AgentRequest.input` goes in the user turn, wrapped and marked as data. `role` and `instructions` go in the system prompt. Tool results are sent back as `tool_result` blocks and are never merged into instructions.
- **Transparency (6).** Every stream chunk, tool call and API call's usage becomes an `AgentEvent`.
- **Small, verifiable steps (7).** No real tools, no cost maths and no secret storage yet.

## Scope
### In scope
- New dependency `anthropic` in `agentic-runtime`.
- New module `agentic_runtime.claude` with `ClaudeRuntime(client: AsyncAnthropic, *, default_model, max_tokens, max_turns, tools: ToolExecutor | None = None)`. `start(request)` returns a `ClaudeRun` (an async iterator plus `cancel()`).
- Request mapping:
  - The system prompt is `role` + `instructions`.
  - The user turn is `input`, wrapped in a clearly delimited data block.
  - The model is `request.model`, or the default model if it is unset.
- Streaming:
  - Text chunks become `text_delta` events.
  - At the end of the turn, the full text becomes one `message` event.
  - Each API call emits one `usage` event (`input_tokens`, `output_tokens`; cache tokens are counted in input). `estimated_usd` stays `None` until 2.1.
- Tool-loop skeleton:
  - A `ToolExecutor` protocol with `definitions(names) -> list[ToolDefinition]` (name, description, JSON Schema input) and `async call(name, arguments) -> ToolOutput`.
  - On `stop_reason == "tool_use"`, the runtime emits `tool_call`, awaits the executor and emits `tool_result`. The result goes back as a `tool_result` block and the loop continues, up to `max_turns`.
  - An executor exception becomes `tool_result(is_error=True)` and the loop goes on.
  - No real tools ship in this phase. Tests use a scripted executor.
- Terminal mapping:
  - `end_turn` → `completed`.
  - `max_tokens`, `refusal`, an unknown stop reason, or `max_turns` exceeded → `failed(retryable=False)` with a clear reason.
  - Errors:
    - Retryable (`failed(retryable=True)`): rate limit (429), overloaded or 5xx, connection errors and timeouts.
    - Not retryable: auth (401/403) and bad request (400).
  - If `request.tools` names a tool and no executor is set, or the executor does not know the tool, the run ends with `failed` before any API call.
- Cancellation:
  - Cooperative cancel, as the 0.3 contract requires.
  - `cancel()` stops the in-flight stream (it closes the HTTP response) and the run yields `cancelled`.
  - Calling it again, or after the run ended, does nothing.
- A shared conformance helper in `agentic_runtime.testing`, for example `async collect_and_check(runtime, request)`. It runs a request, applies `check_events` and returns the events. Both the `FakeRuntime` and `ClaudeRuntime` tests use it.
- Worker wiring:
  - `WorkerSettings` gains:
    - `runtime: Literal["fake", "claude"] = "fake"`
    - `anthropic_api_key: SecretStr | None` (env `ANTHROPIC_API_KEY`)
    - `claude_model`, `claude_max_tokens`, `claude_max_turns`
  - `build_runtime` returns `ClaudeRuntime` when `runtime=claude`. The worker fails fast at startup if the key is missing.
  - `docker-compose.yml` and `.env.example` pass `AGENTIC_RUNTIME` / `ANTHROPIC_API_KEY` through. The default stays `fake`, so CI and `docker compose up` need no key.
- Docs: the README gets a "Run on Claude" section with the manual curl demo. The CHANGELOG gets an entry.

### Out of scope
- Real tools and MCP servers (1.2 `repo` read, 1.6 write tools). This phase only has the loop and a test executor.
- Encrypted, per-workspace API keys and a test that keys never reach logs (1.4).
- Converting tokens into USD (2.1), and budget or policy limits beyond `max_turns` (2.2–2.3).
- Structured output and capability-gap validation (7.3).
- Copilot adapter (7.2). Claude Agent SDK.
- Retrying failed runs. We only set the `retryable` flag. Retries belong to the engine/worker later (1.3).
- Prompt caching, extended thinking and server tools such as web search.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| SDK | `anthropic` Python SDK, Messages API, our own loop | The user chose it. It gives full control over events, and the Claude Agent SDK would put a Node CLI in the worker image. The tech stack allows either option. |
| Streaming | `messages.stream`; emit `text_delta` events, then one `message` | 0.8 must show events within 1 s. Waiting for the final text would hide progress. |
| Tool loop now | Skeleton with an injected `ToolExecutor`; no real tools | The user chose it. It fixes the loop and the event shape before 1.2, so 1.2 only adds an executor. |
| Usage events | One `usage` per API call, tokens only | The contract allows several usage events that add up. USD comes in 2.1. |
| Default model | `claude-sonnet-5-5`, overridable through `CLAUDE_MODEL` and per node through `AgentNode.model` | The tech stack puts Sonnet/Haiku on workers and Opus on hubs and reviewers. A one-node demo is worker-class. |
| Input placement | `role` + `instructions` go in the system prompt; `input` goes in the user turn inside a delimited data block | Mission principle 5. |
| Turn limit | `max_turns` (default 10) → `failed` when it is exceeded | This stops runaway tool loops until the policy limits in 2.2 exist. |
| Runtime selection | `AGENTIC_RUNTIME=fake\|claude`, default `fake` | CI and local compose keep working without a key. |
| API key | `ANTHROPIC_API_KEY` read as `SecretStr` and passed straight to `AsyncAnthropic` | The roadmap says "from env for now". `SecretStr` keeps the key out of reprs and logs until 1.4. |
| Test seam | A real `AsyncAnthropic` with `httpx.MockTransport` replaying recorded SSE bodies | This exercises the real SDK parsing with no network, so the 0.3 `block_network` guard stays on. |

## Open questions
- None
