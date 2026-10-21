# Plan: Claude adapter (API key from env for now)

Order: adapter first, then wiring (the user's choice). Each group leaves `main` green, and the worker defaults to the fake runtime until group 4.

## 1. ClaudeRuntime: streaming, usage, errors, cancel
- [ ] Add `anthropic` to `packages/runtime/pyproject.toml`, then run `uv lock`.
- [ ] Add `packages/runtime/src/agentic_runtime/claude.py` with `ClaudeRuntime` and `ClaudeRun`:
  - [ ] Map `AgentRequest` to the call. `system` is role + instructions. The user turn is `input` in a delimited data block. The model is `request.model or default_model`, and `max_tokens` is set.
  - [ ] Stream with `client.messages.stream(...)`. Emit a `TextDelta` for each text chunk. At the end of the turn, emit one `Message` with the full text and one `Usage` built from `final_message.usage`.
  - [ ] Map stop reasons: `end_turn` → `Completed`. Anything else (for now) → `Failed(retryable=False)` with the reason.
  - [ ] Map errors:
    - `RateLimitError`, `InternalServerError`, overloaded, `APIConnectionError` and `APITimeoutError` → `Failed(retryable=True)`.
    - `AuthenticationError`, `PermissionDeniedError` and `BadRequestError` → `Failed(retryable=False)`.
    - The error text never contains the key.
  - [ ] Cancel: an `asyncio.Event` checked between stream events, and cancelling the in-flight read closes the response. It yields `Cancelled` and is idempotent.
- [ ] Export `ClaudeRuntime` from `agentic_runtime/__init__.py`.
- [ ] Tests in `packages/runtime/tests/test_claude_runtime.py`:
  - [ ] Add an `httpx.MockTransport` helper that replays SSE fixtures from `packages/runtime/tests/fixtures/claude/*.sse` (text turn, tool-use turn, max_tokens, refusal).
  - [ ] Cover request mapping, delta/message/usage, each error class, and cancel before, during and after the run.

## 2. Tool-loop skeleton
- [ ] Add `agentic_runtime/tools.py`:
  - [ ] `ToolDefinition`: name, description, `input_schema` as JSON Schema.
  - [ ] `ToolOutput`: text plus `is_error`.
  - [ ] `ToolExecutor` Protocol with `definitions(names)` and `async call(name, arguments)`.
- [ ] `ClaudeRuntime` takes an optional `tools: ToolExecutor`:
  - [ ] Before the first API call, resolve `request.tools` through `definitions`. A missing executor or an unknown name → `Failed` with no API call.
  - [ ] Pass the definitions as Messages API `tools`.
  - [ ] On `stop_reason == "tool_use"`: emit `ToolCall` per block, await `call`, then emit `ToolResult`. An exception becomes `is_error=True`.
  - [ ] Append the assistant content and the `tool_result` blocks, then loop.
  - [ ] Emit `Usage` after each API call. More than `max_turns` turns → `Failed("max turns exceeded")`.
- [ ] Add a `ScriptedToolExecutor` to `agentic_runtime.testing`. It takes a dict of name to output or exception.
- [ ] Tests:
  - [ ] A two-turn tool run, with event order call → result → message → completed.
  - [ ] Executor error turned into `is_error`.
  - [ ] Unknown tool, and a tool listed with no executor.
  - [ ] `max_turns` exceeded.
  - [ ] Cancel while a tool call is waiting.

## 3. Shared conformance helper
- [ ] Add `async collect_and_check(runtime, request) -> list[AgentEvent]` to `agentic_runtime.testing`. It iterates the run, calls `check_events` and returns the events.
- [ ] Use it in `test_fake_runtime.py` and in every terminal-path test in `test_claude_runtime.py`, so both adapters are held to the same 0.3 contract.

## 4. Worker wiring and config
- [ ] Add to `WorkerSettings` (`packages/worker/src/agentic_worker/main.py`):
  - `runtime: Literal["fake", "claude"] = "fake"` (env `AGENTIC_RUNTIME`)
  - `anthropic_api_key: SecretStr | None`
  - `claude_model = "claude-sonnet-5-5"`, `claude_max_tokens = 4096`, `claude_max_turns = 10`
- [ ] `build_runtime`: for `claude`, build an `AsyncAnthropic(api_key=...)` and return `ClaudeRuntime` (no tool executor yet). A missing key raises a clear startup error that does not echo any setting values.
- [ ] Update the module docstring, which still says "runs use the fake runtime".
- [ ] Pass `AGENTIC_RUNTIME`, `ANTHROPIC_API_KEY` and `CLAUDE_MODEL` through `docker-compose.yml` (worker service), with `fake` as the default. Add commented entries to `.env.example`.
- [ ] Worker tests:
  - [ ] `build_runtime` picks fake or Claude.
  - [ ] It fails fast without a key.
  - [ ] An end-to-end test (worker → engine → `ClaudeRuntime` on `MockTransport`) shows a one-node run storing `text_delta`/`message`/`usage` events and `run_completed` in Postgres (integration marker, Testcontainers).

## 5. Docs and manual demo
- [ ] README: add a "Run on Claude" section (set the env vars, `docker compose up`, `POST /runs` with a one-node spec fixture, `curl -N` the events URL) and the expected output.
- [ ] Add a one-node spec fixture `packages/engine/tests/fixtures/specs/one-agent.json`, or reuse one if it already exists.
- [ ] CHANGELOG entry. Run the manual check in `validation.md` and note the result on the PR.
