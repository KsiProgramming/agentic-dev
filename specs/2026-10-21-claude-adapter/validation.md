# Validation: Claude adapter (API key from env for now)

## Done when (from roadmap)
> A one-node run on Claude returns text and a usage event

CI proves the adapter with deterministic tests: a real `AsyncAnthropic` client on an in-memory `httpx2.MockTransport` (`agentic_runtime.testing.MockClaude`), with no network (`block_network` stays on). One manual check against the real API proves "on Claude" before merge (the user's choice). No live test code is added.

## Automated checks
Unit tests in `packages/runtime/tests/test_claude_runtime.py`. Each terminal path goes through `collect_and_check`, so `check_events` passes on every stream.

- [x] `test_text_turn_streams_deltas_then_usage_message_completed`: the events are `text_delta`+, then `usage` (tokens from the reply), then `message` (text = joined deltas), then `completed`.
- [x] `test_request_mapping`: the recorded HTTP body has `system` = role + instructions, the user turn holds `input` in the data block, the model defaults to `claude-sonnet-5-5`, `AgentRequest.model` overrides it, `max_tokens` is set, and no `tools` are sent when none are requested.
- [x] `test_retryable_errors`, parametrised over 429, 500, 503, 529, connection error and timeout: each gives `failed(retryable=True)` with no key in the error text.
- [x] `test_non_retryable_errors`, parametrised over 400, 401 and 403: each gives `failed(retryable=False)` with the API's message.
- [x] `test_max_tokens_and_refusal_fail`: each gives `usage`, then `failed(retryable=False)` with the stop reason in `error`.
- [x] Cancel tests:
  - `test_cancel_before_iteration_yields_only_cancelled`: no API call is made.
  - `test_cancel_while_the_stream_stalls_closes_the_response`: the stream ends with `cancelled` and the response is closed. Calling cancel twice is safe.
  - `test_cancel_after_completed_is_a_no_op`
  - `test_cancel_while_a_tool_runs`
- [x] `test_tool_loop_two_turns`: the order is `text_delta` → `usage` → `tool_call` → `tool_result` → `text_delta` → `usage` → `message` → `completed`. The tool is sent as `repo__read_file` and mapped back to `repo.read_file`. The second request carries the `tool_result` block.
- [x] `test_tool_errors_are_reported_and_the_loop_continues`: an exception and an `is_error` output both give `tool_result(is_error=True)`, and the run still completes.
- [x] `test_tools_that_cannot_be_offered_fail_before_any_call`: no executor, an unknown tool, or an invalid name; the transport records 0 requests.
- [x] `test_max_turns_exceeded_fails`
- [x] `test_fake_runtime.py` uses `collect_and_check` and still passes.

Worker tests (`packages/worker/tests`):
- [x] `test_build_runtime.py`:
  - `test_the_fake_runtime_is_the_default`
  - `test_agentic_runtime_claude_selects_the_claude_runtime`
  - `test_the_runtime_can_be_set_by_field_name`
  - `test_claude_without_a_key_fails_fast`
  - `test_the_key_is_hidden_in_the_settings_repr`
- [x] `test_a_one_node_run_on_claude_stores_text_and_usage` (integration, Testcontainers Postgres + Redis): the worker runs `single-agent.json` through `ClaudeRuntime` on `MockClaude`. The node's `run_events` are `node_started`, `text_delta` ×2, `usage`, `message`, `completed` and `node_completed`, followed by `run_completed`. No event payload contains the key.

Static checks: `ruff check`, `ruff format --check`, `pyright` (strict) and the full `pytest` suite are green in CI.

## Manual / demo checks
One check before merge, run by the author with a real key:

- [ ] `AGENTIC_RUNTIME=claude ANTHROPIC_API_KEY=<key> docker compose up -d --build`
- [ ] The README's "Run on Claude" `curl -X POST /runs` returns 202 with `events_url`.
- [ ] `curl -N <events_url>` streams `run_started`, several `text_delta` frames arriving over time, a `usage` with non-zero `input_tokens`/`output_tokens`, one `message` with real Claude text, then `run_completed`.
- [ ] `docker compose logs worker api | grep -c "<first 12 chars of key>"` prints `0`.
- [ ] The result (an excerpt of the stream, with no key) is pasted in the PR description.

## Merge criteria
- [ ] All automated checks above pass in CI. CI needs no Anthropic key, and the default runtime stays `fake`.
- [ ] The manual check is done and its output is on the PR.
- [x] README sections "Claude adapter" and "Run on Claude", `.env.example` and CHANGELOG are updated.
- [x] The API key appears in no log line, event payload, exception message or settings repr (`SecretStr`; covered by the tests above).
- [ ] Roadmap phase 0.7 is marked done (`complete-phase`).
