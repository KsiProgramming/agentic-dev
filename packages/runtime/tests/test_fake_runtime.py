import asyncio
import socket
import time

import pytest

from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    AgentRuntime,
    Cancelled,
    Completed,
    Failed,
    Message,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
    check_events,
)
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime, slow_echo_script
from agentic_runtime.testing import NetworkBlockedError

USAGE = Usage(input_tokens=3, output_tokens=4)


def request(node_id: str = "writer", input: str = "hello") -> AgentRequest:
    return AgentRequest(node_id=node_id, role="Writer", instructions="Write.", input=input)


async def collect(runtime: AgentRuntime, req: AgentRequest) -> list[AgentEvent]:
    return [event async for event in runtime.start(req)]


async def test_default_script_echoes_the_input() -> None:
    events = await collect(FakeRuntime(), request(input="ping"))
    assert events == [Message(text="ping"), ECHO_USAGE, Completed()]


async def test_slow_echo_streams_word_deltas_over_time() -> None:
    runtime = FakeRuntime(default=lambda text: slow_echo_script(text, 0.01))

    started = time.monotonic()
    events = await collect(runtime, request(input="hello big world"))

    assert events == [
        TextDelta(text="hello "),
        TextDelta(text="big "),
        TextDelta(text="world"),
        Message(text="hello big world"),
        ECHO_USAGE,
        Completed(),
    ]
    assert time.monotonic() - started >= 0.05


async def test_scripts_are_chosen_per_node_id() -> None:
    runtime = FakeRuntime({"reviewer": [Message(text="LGTM"), USAGE]})
    reviewed = await collect(runtime, request("reviewer"))
    echoed = await collect(runtime, request("writer", input="draft"))
    assert reviewed == [Message(text="LGTM"), USAGE, Completed()]
    assert echoed[0] == Message(text="draft")


async def test_tool_call_then_result() -> None:
    script = [
        ToolCall(call_id="c1", name="repo.read_file", arguments={"path": "README.md"}),
        ToolResult(call_id="c1", output="# Readme"),
        Message(text="It is a readme."),
        USAGE,
    ]
    events = await collect(FakeRuntime({"writer": script}), request())
    assert events == [*script, Completed()]


async def test_scripted_failure() -> None:
    events = await collect(FakeRuntime({"writer": [Failed(error="rate limited")]}), request())
    assert events == [Failed(error="rate limited")]


@pytest.mark.parametrize(
    "script",
    [
        [Message(text="hi"), USAGE],
        [ToolCall(call_id="c1", name="t"), ToolResult(call_id="c1", output=""), USAGE],
        [Failed(error="x")],
        [Delay(0), Message(text="hi"), Cancelled()],
    ],
)
async def test_every_stream_has_exactly_one_terminal_event_last(script: list[AgentEvent]) -> None:
    events = await collect(FakeRuntime({"writer": script}), request())
    check_events(events)


async def test_requests_are_recorded() -> None:
    runtime = FakeRuntime()
    await collect(runtime, request("a"))
    await collect(runtime, request("b"))
    assert [r.node_id for r in runtime.requests] == ["a", "b"]


@pytest.mark.parametrize(
    ("script", "msg"),
    [
        ([], "without a usage event"),
        ([Message(text="hi")], "without a usage event"),
        ([ToolResult(call_id="c9", output=""), USAGE], "has no tool_call"),
        ([USAGE, Completed(), Message(text="late")], "after the terminal event"),
    ],
)
def test_invalid_scripts_are_rejected(script: list[AgentEvent], msg: str) -> None:
    with pytest.raises(ValueError, match=rf"script for node 'writer': .*{msg}"):
        FakeRuntime({"writer": script})


def test_a_run_is_iterated_once() -> None:
    run = FakeRuntime().start(request())
    aiter(run)
    with pytest.raises(RuntimeError, match="only be iterated once"):
        aiter(run)


async def test_cancel_before_iteration_yields_only_cancelled() -> None:
    run = FakeRuntime().start(request())
    run.cancel()
    assert [e async for e in run] == [Cancelled()]


async def test_cancel_during_a_delay_stops_promptly() -> None:
    run = FakeRuntime({"writer": [Message(text="a"), Delay(30), Message(text="b"), USAGE]}).start(
        request()
    )
    events: list[AgentEvent] = []
    started = time.monotonic()

    async def consume() -> None:
        async for event in run:
            events.append(event)
            if event == Message(text="a"):
                asyncio.get_running_loop().call_later(0.01, run.cancel)

    await asyncio.wait_for(consume(), timeout=5)
    assert events == [Message(text="a"), Cancelled()]
    assert time.monotonic() - started < 0.1


async def test_cancel_after_completed_is_a_no_op() -> None:
    run = FakeRuntime().start(request())
    events = [e async for e in run]
    run.cancel()
    run.cancel()
    assert events[-1] == Completed()


async def test_double_cancel_is_idempotent() -> None:
    run = FakeRuntime({"writer": [Message(text="a"), Delay(30), USAGE]}).start(request())
    events: list[AgentEvent] = []
    async for event in run:
        events.append(event)
        run.cancel()
        run.cancel()
    assert events == [Message(text="a"), Cancelled()]


def test_no_network_guard_blocks_outbound_connections() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(NetworkBlockedError), socket.socket() as sock:
        sock.connect(("93.184.215.14", 443))


async def test_no_network_guard_allows_loopback() -> None:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
