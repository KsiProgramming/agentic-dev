# Plan: Claude adapter (API key from env for now)

Order: adapter first, then wiring (the user's choice). Each group leaves `main` green, and the worker defaults to the fake runtime until group 4.

## 1. ClaudeRuntime: streaming, usage, errors, cancel
- [x] Add `anthropic` (≥ 1.17) and `httpx2` (the SDK's HTTP client, used by the test transport) to `packages/runtime/pyproject.toml`, then run `uv lock`.
- [x] Add `packages/runtime/src/agentic_runtime/claude.py` with `ClaudeRuntime` and `ClaudeRun`:
  - [x] Map `AgentRequest` to the call. `system` is `Your role: <role>` + instructions. The user turn is `input` in an `<input>` block marked as data. The model is `request.model or default_model`, and `max_tokens` is set.
  - [x] Stream with `client.messages.stream(...)`. Emit a `TextDelta` for each text chunk. After each API call, emit one `Usage` built from `final_message.usage` (cache tokens counted as input). On `end_turn`/`stop_sequence`, emit `Message` with the final turn's text, then `Completed`.
  - [x] Map stop reasons: `end_turn`/`stop_sequence` → `Completed`. Anything else (`max_tokens`, `refusal`, …) → `Failed(retryable=False)` with the reason.
  - [x] Map errors:
    - Connection errors, timeouts, and status 408/409/429/5xx (including 529 overloaded) → `Failed(retryable=True)`.
    - Other statuses (400/401/403/…) → `Failed(retryable=False)`.
    - The error text is the API's own message, never the request, so it never contains the key.
  - [x] Cancel: every wait (next stream event, tool call) races the cancel event. Cancelling the in-flight read closes the response through the stream's context manager. It yields `Cancelled` and is idempotent.
- [x] Export `ClaudeRuntime` (and the tool types) from `agentic_runtime/__init__.py`.
- [x] Add `MockClaude` to `agentic_runtime.testing`: a real `AsyncAnthropic` on `httpx2.MockTransport` that replays scripted SSE replies (`text_reply`, `tool_use_reply`, `error_reply`, transport errors, `hang`) and records request bodies. Builders replaced recorded `.sse` fixture files, because they are easier to read in tests.
- [x] Tests in `packages/runtime/tests/test_claude_runtime.py`: request mapping, delta/usage/message, each error class, and cancel before, during and after the run.

## 2. Tool-loop skeleton
- [x] Add `agentic_runtime/tools.py`:
  - [x] `ToolDefinition`: name, description, `input_schema` as JSON Schema.
  - [x] `ToolOutput`: text plus `is_error`.
  - [x] `ToolExecutor` Protocol with `definitions()` (every tool it offers) and `async call(name, arguments)`.
- [x] `ClaudeRuntime` takes an optional `tools: ToolExecutor`:
  - [x] Before the first API call, resolve `request.tools` against `definitions()`. A missing executor, an unknown name, or a name the API cannot carry → `Failed` with no API call.
  - [x] Pass the definitions as Messages API `tools`. Dots in platform names are sent as `__` (`repo.read_file` → `repo__read_file`) and mapped back on `tool_use`.
  - [x] On `stop_reason == "tool_use"`: emit `ToolCall` per block, await `call`, then emit `ToolResult`. An exception becomes `is_error=True`.
  - [x] Append the assistant content and the `tool_result` blocks, then loop.
  - [x] Emit `Usage` after each API call. More than `max_turns` API calls → `Failed("max turns exceeded (N)")`.
- [x] Add a `ScriptedToolExecutor` to `agentic_runtime.testing`. It takes a dict of name to output text, `ToolOutput` or exception, and has an optional `gate` to hold calls.
- [x] Tests:
  - [x] A two-turn tool run, with the event order and the second request's `tool_result` block checked.
  - [x] Executor error and an `is_error` output.
  - [x] Unknown tool, a tool listed with no executor, and an invalid name.
  - [x] `max_turns` exceeded.
  - [x] Cancel while a tool call is waiting.

## 3. Shared conformance helper
- [x] Add `async collect_and_check(runtime, request) -> list[AgentEvent]` to `agentic_runtime.testing`. It iterates the run, calls `check_events` and returns the events.
- [x] Use it in `test_fake_runtime.py` and in every terminal-path test in `test_claude_runtime.py`, so both adapters are held to the same 0.3 contract.

## 4. Worker wiring and config
- [x] Add to `WorkerSettings` (`packages/worker/src/agentic_worker/main.py`):
  - `runtime: Literal["fake", "claude"] = "fake"` (env `AGENTIC_RUNTIME`)
  - `anthropic_api_key: SecretStr | None`
  - `claude_model` (default `claude-sonnet-5-5`), `claude_max_tokens` (default 4096), `claude_max_turns` (default 10)
- [x] `build_runtime`: for `claude`, build an `AsyncAnthropic(api_key=...)` and return `ClaudeRuntime` (no tool executor yet). A missing or empty key raises `ConfigError` with no setting values in it.
- [x] Update the module docstring.
- [x] Pass `AGENTIC_RUNTIME`, `ANTHROPIC_API_KEY` and `CLAUDE_MODEL` through `docker-compose.yml` (worker service), with `fake` as the default. Add commented entries to `.env.example`.
- [x] Worker tests:
  - [x] `test_build_runtime.py`: fake is the default, env selects Claude, a missing key fails fast, and the key is hidden in the settings repr.
  - [x] `test_a_one_node_run_on_claude_stores_text_and_usage` (integration): the worker runs `single-agent.json` through `ClaudeRuntime` on `MockClaude`, and `run_events` holds `text_delta`, `usage`, `message`, `completed` and `run_completed`.

## 5. Docs and manual demo
- [x] README: add a "Claude adapter" section under Agent runtime and a "Run on Claude" section under Runs API (env vars, `docker compose up`, `POST /runs` with `single-agent.json`, `curl -N` the events URL, expected output).
- [x] Reuse the existing one-node fixture `packages/engine/tests/fixtures/specs/valid/single-agent.json`.
- [x] CHANGELOG entry.
- [ ] Run the manual check in `validation.md` with a real key and note the result on the PR.
