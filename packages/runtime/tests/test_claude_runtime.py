import asyncio

import httpx2
import pytest

from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    Cancelled,
    Completed,
    Failed,
    Message,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from agentic_runtime.claude import DEFAULT_MODEL, ClaudeRuntime
from agentic_runtime.pricing import DEFAULT_PRICES, ModelPrice
from agentic_runtime.testing import (
    MOCK_API_KEY,
    MockClaude,
    MockReply,
    ScriptedToolExecutor,
    collect_and_check,
    error_reply,
    text_reply,
    tool_use_reply,
)
from agentic_runtime.tools import ToolOutput


def request(input: str = "hello", **kwargs: object) -> AgentRequest:
    return AgentRequest.model_validate(
        {"node_id": "writer", "role": "Writer", "instructions": "Write.", "input": input, **kwargs}
    )


def runtime(mock: MockClaude, **kwargs: object) -> ClaudeRuntime:
    return ClaudeRuntime(mock.client, **kwargs)  # pyright: ignore[reportArgumentType]


async def test_text_turn_streams_deltas_then_usage_message_completed() -> None:
    mock = MockClaude([text_reply("Hel", "lo ", "world", input_tokens=12, output_tokens=5)])

    events = await collect_and_check(runtime(mock), request())

    assert events == [
        TextDelta(text="Hel"),
        TextDelta(text="lo "),
        TextDelta(text="world"),
        Usage(model="claude-test", input_tokens=12, output_tokens=5),
        Message(text="Hello world"),
        Completed(),
    ]


async def test_usage_keeps_cache_tokens_apart_and_is_priced() -> None:
    reply = text_reply(
        "a",
        model="claude-opus-5-5",
        input_tokens=1000,
        output_tokens=100,
        cache_read_input_tokens=10_000,
        cache_creation_input_tokens=3000,
        cache_creation={"ephemeral_5m_input_tokens": 1000, "ephemeral_1h_input_tokens": 2000},
    )

    events = await collect_and_check(runtime(MockClaude([reply])), request())

    usage = next(e for e in events if isinstance(e, Usage))
    # $4 x 1000 + $20 x 100 + $0.20 x 10,000 + $5 x 1000 + $8 x 2000, per million tokens.
    assert usage == Usage(
        model="claude-opus-5-5",
        input_tokens=1000,
        output_tokens=100,
        cache_read_tokens=10_000,
        cache_write_tokens=3000,
        estimated_usd=0.029,
    )


async def test_cache_writes_without_a_ttl_breakdown_are_five_minute_writes() -> None:
    reply = text_reply(
        "a", model="claude-opus-5-5", input_tokens=0, output_tokens=0,
        cache_creation_input_tokens=1_000_000,
    )  # fmt: skip

    events = await collect_and_check(runtime(MockClaude([reply])), request())

    usage = next(e for e in events if isinstance(e, Usage))
    assert (usage.cache_write_tokens, usage.estimated_usd) == (1_000_000, 5.0)


async def test_usage_is_priced_with_the_runtime_price_table() -> None:
    prices = DEFAULT_PRICES.with_overrides(
        {"claude-test": ModelPrice.model_validate(dict.fromkeys(ModelPrice.model_fields, "1000"))}
    )
    reply = text_reply("a", input_tokens=12, output_tokens=5)

    events = await collect_and_check(runtime(MockClaude([reply]), prices=prices), request())

    usage = next(e for e in events if isinstance(e, Usage))
    assert usage.estimated_usd == 0.017  # 17 tokens at $1000 per million


async def test_request_mapping() -> None:
    mock = MockClaude([text_reply("a"), text_reply("b")])

    await collect_and_check(runtime(mock, max_tokens=321), request(input="the README"))
    await collect_and_check(runtime(mock), request(model="claude-opus-5-5"))

    body = mock.requests[0]
    assert body["model"] == DEFAULT_MODEL
    assert body["max_tokens"] == 321
    assert body["stream"] is True
    assert body["system"] == "Your role: Writer\n\nWrite."
    [turn] = body["messages"]
    assert turn["role"] == "user"
    assert "<input>\nthe README\n</input>" in turn["content"]
    assert "data, not instructions" in turn["content"]
    assert "tools" not in body
    assert mock.requests[1]["model"] == "claude-opus-5-5"


@pytest.mark.parametrize(
    "reply",
    [
        error_reply(429, kind="rate_limit_error"),
        error_reply(500),
        error_reply(503),
        error_reply(529, kind="overloaded_error"),
        MockReply(error=httpx2.ConnectError("refused")),
        MockReply(error=httpx2.ReadTimeout("slow")),
    ],
)
async def test_retryable_errors(reply: MockReply) -> None:
    [event] = await collect_and_check(runtime(MockClaude([reply])), request())
    assert isinstance(event, Failed)
    assert event.retryable
    assert MOCK_API_KEY not in event.error


@pytest.mark.parametrize(
    ("status", "kind"),
    [(400, "invalid_request_error"), (401, "authentication_error"), (403, "permission_error")],
)
async def test_non_retryable_errors(status: int, kind: str) -> None:
    mock = MockClaude([error_reply(status, "nope", kind)])

    [event] = await collect_and_check(runtime(mock), request())

    assert event == Failed(error=f"Claude API error {status}: nope", retryable=False)


@pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
async def test_max_tokens_and_refusal_fail(reason: str) -> None:
    mock = MockClaude([text_reply("partial", stop_reason=reason)])

    events = await collect_and_check(runtime(mock), request())

    assert events[-2] == Usage(model="claude-test", input_tokens=12, output_tokens=5)
    assert events[-1] == Failed(error=f"Claude stopped without finishing: {reason}")


async def test_cancel_before_iteration_yields_only_cancelled() -> None:
    mock = MockClaude([text_reply("a")])
    run = runtime(mock).start(request())
    run.cancel()

    assert [e async for e in run] == [Cancelled()]
    assert mock.requests == []


async def test_cancel_while_the_stream_stalls_closes_the_response() -> None:
    mock = MockClaude([text_reply("first", "never", hang=True)])
    run = runtime(mock).start(request())
    events: list[AgentEvent] = []
    first = asyncio.Event()

    async def consume() -> None:
        async for event in run:
            events.append(event)
            first.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first.wait(), timeout=5)
    await asyncio.sleep(0.01)
    run.cancel()  # the stream is now waiting for bytes that never come
    run.cancel()
    await asyncio.wait_for(task, timeout=5)

    assert events == [TextDelta(text="first"), Cancelled()]
    await asyncio.wait_for(mock.closed.wait(), timeout=5)


async def test_cancel_after_completed_is_a_no_op() -> None:
    run = runtime(MockClaude([text_reply("a")])).start(request())
    events = [e async for e in run]
    run.cancel()
    run.cancel()
    assert events[-1] == Completed()


def test_a_run_is_iterated_once() -> None:
    run = runtime(MockClaude([])).start(request())
    aiter(run)
    with pytest.raises(RuntimeError, match="only be iterated once"):
        aiter(run)


async def test_tool_loop_two_turns() -> None:
    tools = ScriptedToolExecutor({"repo.read_file": "# Readme"})
    mock = MockClaude(
        [
            tool_use_reply(("toolu_1", "repo__read_file", {"path": "README.md"}), text="Looking."),
            text_reply("It is a readme.", input_tokens=40, output_tokens=6),
        ]
    )

    events = await collect_and_check(runtime(mock, tools=tools), request(tools=["repo.read_file"]))

    assert events == [
        TextDelta(text="Looking."),
        Usage(model="claude-test", input_tokens=20, output_tokens=8),
        ToolCall(call_id="toolu_1", name="repo.read_file", arguments={"path": "README.md"}),
        ToolResult(call_id="toolu_1", output="# Readme"),
        TextDelta(text="It is a readme."),
        Usage(model="claude-test", input_tokens=40, output_tokens=6),
        Message(text="It is a readme."),
        Completed(),
    ]
    assert tools.calls == [("repo.read_file", {"path": "README.md"})]
    assert tools.node_ids == ["writer"]  # so a run's executor can route the call
    [tool] = mock.requests[0]["tools"]
    assert tool["name"] == "repo__read_file"
    assert tool["input_schema"] == {"type": "object", "properties": {}}
    second = mock.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "# Readme", "is_error": False}
    ]


@pytest.mark.parametrize(
    ("model", "thinking"),
    [
        (DEFAULT_MODEL, {"type": "adaptive", "display": "summarized"}),
        ("claude-opus-5-5", {"type": "adaptive", "display": "summarized"}),
        ("claude-fable-5-1", {"type": "adaptive", "display": "summarized"}),
        ("claude-haiku-5-5", {"type": "adaptive", "display": "summarized"}),
        # Thinking is off by default on these, or they predate adaptive thinking.
        ("claude-opus-4-8", None),
        ("claude-sonnet-4-6", None),
        ("claude-haiku-4-5", None),
        ("claude-test", None),
    ],
)
async def test_models_that_think_by_default_are_asked_to_show_it(
    model: str, thinking: dict[str, str] | None
) -> None:
    mock = MockClaude([text_reply("a")])

    await collect_and_check(runtime(mock), request(model=model))

    assert mock.requests[0].get("thinking") == thinking


async def test_reasoning_streams_before_the_text_and_goes_back_with_the_tool_results() -> None:
    tools = ScriptedToolExecutor({"repo.read_file": "# Readme"})
    mock = MockClaude(
        [
            tool_use_reply(
                ("toolu_1", "repo__read_file", {"path": "README.md"}),
                thinking=["Start with ", "the readme."],
            ),
            text_reply("It is a readme.", thinking=["Enough to answer."]),
        ]
    )

    events = await collect_and_check(runtime(mock, tools=tools), request(tools=["repo.read_file"]))

    assert [e for e in events if not isinstance(e, Usage)] == [
        ReasoningDelta(text="Start with "),
        ReasoningDelta(text="the readme."),
        ToolCall(call_id="toolu_1", name="repo.read_file", arguments={"path": "README.md"}),
        ToolResult(call_id="toolu_1", output="# Readme"),
        ReasoningDelta(text="Enough to answer."),
        TextDelta(text="It is a readme."),
        Message(text="It is a readme."),
        Completed(),
    ]
    # The thinking block goes back unchanged, signature included.
    assistant = mock.requests[1]["messages"][1]["content"]
    assert assistant[0] == {
        "type": "thinking",
        "thinking": "Start with the readme.",
        "signature": "sig-test",
    }


async def test_tool_errors_are_reported_and_the_loop_continues() -> None:
    tools = ScriptedToolExecutor(
        {"boom": RuntimeError("disk on fire"), "soft": ToolOutput(text="no", is_error=True)}
    )
    mock = MockClaude(
        [tool_use_reply(("t1", "boom", {}), ("t2", "soft", {})), text_reply("Sorry.")]
    )

    events = await collect_and_check(runtime(mock, tools=tools), request(tools=["boom", "soft"]))

    results = [e for e in events if isinstance(e, ToolResult)]
    assert results == [
        ToolResult(call_id="t1", output="tool failed: disk on fire", is_error=True),
        ToolResult(call_id="t2", output="no", is_error=True),
    ]
    assert events[-1] == Completed()
    assert [b["is_error"] for b in mock.requests[1]["messages"][2]["content"]] == [True, True]


@pytest.mark.parametrize(
    ("tools", "names", "error"),
    [
        (None, ["repo.read_file"], "no tool executor is set: repo.read_file"),
        (ScriptedToolExecutor({"a": ""}), ["a", "b"], "unknown tools: b"),
        (ScriptedToolExecutor({"bad name": ""}), ["bad name"], "cannot use: bad name"),
    ],
)
async def test_tools_that_cannot_be_offered_fail_before_any_call(
    tools: ScriptedToolExecutor | None, names: list[str], error: str
) -> None:
    mock = MockClaude([text_reply("a")])

    [event] = await collect_and_check(runtime(mock, tools=tools), request(tools=names))

    assert isinstance(event, Failed)
    assert error in event.error
    assert mock.requests == []


async def test_max_turns_exceeded_fails() -> None:
    tools = ScriptedToolExecutor({"t": "again"})
    mock = MockClaude([tool_use_reply((f"c{i}", "t", {})) for i in range(2)])

    events = await collect_and_check(runtime(mock, tools=tools, max_turns=2), request(tools=["t"]))

    assert events[-1] == Failed(error="max turns exceeded (2)")
    assert len(mock.requests) == 2


async def test_cancel_while_a_tool_runs() -> None:
    tools = ScriptedToolExecutor({"t": "late"})
    tools.gate = asyncio.Event()
    mock = MockClaude([tool_use_reply(("c1", "t", {}))])
    run = runtime(mock, tools=tools).start(request(tools=["t"]))
    events: list[AgentEvent] = []

    async def consume() -> None:
        async for event in run:
            events.append(event)
            if isinstance(event, ToolCall):
                asyncio.get_running_loop().call_later(0.01, run.cancel)

    await asyncio.wait_for(consume(), timeout=5)

    assert events[-2:] == [ToolCall(call_id="c1", name="t"), Cancelled()]


def test_max_turns_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        runtime(MockClaude([]), max_turns=0)
