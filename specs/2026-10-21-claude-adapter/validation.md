# Validation: Claude adapter (API key from env for now)

## Done when (from roadmap)
> A one-node run on Claude returns text and a usage event

CI proves the adapter with deterministic tests: a real `AsyncAnthropic` client on `httpx.MockTransport`, with no network (`block_network` stays on). One manual check against the real API proves "on Claude" before merge (the user's choice). No live test code is added.

## Automated checks
Unit tests in `packages/runtime/tests/test_claude_runtime.py`. Each terminal path goes through `collect_and_check`, so `check_events` passes on every stream.

- [ ] `test_text_turn_streams_deltas_then_message_usage_completed`: the events are `text_delta`+, then `message` (text = joined deltas), then `usage` (tokens from the fixture), then `completed`.
- [ ] `test_request_mapping`: the recorded HTTP body has `system` = role + instructions, the user turn holds `input` in the data block, the model defaults to `claude-sonnet-5-5`, `AgentRequest.model` overrides it, and `max_tokens` is set.
- [ ] `test_retryable_errors`, parametrised over 429, 529/5xx, connection error and timeout: each gives `failed(retryable=True)`.
- [ ] `test_non_retryable_errors`, parametrised over 400, 401 and 403: each gives `failed(retryable=False)`, and the error text does not contain the API key.
- [ ] `test_max_tokens_and_refusal_fail`: each gives `failed(retryable=False)` with the stop reason in `error`.
- [ ] `test_cancel_before_during_after`: cancel before iteration → only `cancelled`. Cancel mid-stream → `cancelled` and the response is closed. Cancel after `completed` → no-op. Calling cancel twice is safe.
- [ ] `test_tool_loop_two_turns`: the order is `tool_call` → `tool_result` → … → `message` → `completed`, with `usage` once per API call. The second request carries the `tool_result` block.
- [ ] `test_tool_executor_error_is_reported_and_loop_continues`: an exception gives `tool_result(is_error=True)` and the run still completes.
- [ ] `test_unknown_or_unconfigured_tool_fails_before_any_call`: the transport records 0 requests.
- [ ] `test_max_turns_exceeded_fails`
- [ ] `test_fake_runtime.py` uses `collect_and_check` and still passes.

Worker tests (`packages/worker/tests`):
- [ ] `test_build_runtime_selects_fake_by_default_and_claude_when_configured`
- [ ] `test_claude_runtime_without_key_fails_fast`: a clear error with no setting values echoed.
- [ ] `test_one_node_run_on_claude_mock_stores_text_and_usage` (integration, Testcontainers Postgres + Redis): the worker runs a one-node spec through `ClaudeRuntime` on `MockTransport`. `run_events` holds `text_delta`, `message`, `usage` and `run_completed` in order, and `runs.status` = `completed`.

Static checks: `ruff check`, `ruff format --check`, `pyright` (strict) and the full `pytest` suite are green in CI.

## Manual / demo checks
One check before merge, run by the author with a real key:

- [ ] `AGENTIC_RUNTIME=claude ANTHROPIC_API_KEY=<key> docker compose up -d --build`
- [ ] `curl -s -X POST localhost:8000/runs -H 'content-type: application/json' -d @<one-agent request>` returns 202 with `events_url`.
- [ ] `curl -N localhost:8000<events_url>` streams `run_started`, several `text_delta` frames arriving over time, one `message` with real Claude text, a `usage` with non-zero `input_tokens`/`output_tokens`, then `run_completed`.
- [ ] `docker compose logs worker api | grep -c "<first 8 chars of key>"` prints `0`.
- [ ] The result (an excerpt of the stream, with no key) is pasted in the PR description.

## Merge criteria
- [ ] All automated checks above pass in CI. CI needs no Anthropic key, and the default runtime stays `fake`.
- [ ] The manual check is done and its output is on the PR.
- [ ] README "Run on Claude" section, `.env.example` and CHANGELOG are updated.
- [ ] The API key appears in no log line, event payload, exception message or settings repr.
- [ ] Roadmap phase 0.7 is marked done (`complete-phase`).
