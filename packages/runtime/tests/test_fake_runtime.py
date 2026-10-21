import asyncio
import socket
import time

import pytest

from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    Cancelled,
    Completed,
    Failed,
    Message,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
)
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, slow_echo_script
from agentic_runtime.testing import NetworkBlockedError, ScriptedToolExecutor, collect_and_check
from agentic_runtime.tools import ToolOutput

USAGE = Usage(input_tokens=3, output_tokens=4)


def request(node_id: str = "writer", input: str = "hello") -> AgentRequest:
    return AgentRequest(node_id=node_id, role="Writer", instructions="Write.", input=input)


async def test_default_script_echoes_the_input() -> None:
    events = await collect_and_check(FakeRuntime(), request(input="ping"))
    assert events == [Message(text="ping"), ECHO_USAGE, Completed()]


async def test_slow_echo_streams_word_deltas_over_time() -> None:
    runtime = FakeRuntime(default=lambda text: slow_echo_script(text, 0.01))

    started = time.monotonic()
    events = await collect_and_check(runtime, request(input="hello big world"))

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
    reviewed = await collect_and_check(runtime, request("reviewer"))
    echoed = await collect_and_check(runtime, request("writer", input="draft"))
    assert reviewed == [Message(text="LGTM"), USAGE, Completed()]
    assert echoed[0] == Message(text="draft")


async def test_tool_call_then_result() -> None:
    script = [
        ToolCall(call_id="c1", name="repo.read_file", arguments={"path": "README.md"}),
        ToolResult(call_id="c1", output="# Readme"),
        Message(text="It is a readme."),
        USAGE,
    ]
    events = await collect_and_check(FakeRuntime({"writer": script}), request())
    assert events == [*script, Completed()]


async def test_scripted_failure() -> None:
    events = await collect_and_check(
        FakeRuntime({"writer": [Failed(error="rate limited")]}), request()
    )
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
    await collect_and_check(FakeRuntime({"writer": script}), request())


async def test_requests_are_recorded() -> None:
    runtime = FakeRuntime()
    await collect_and_check(runtime, request("a"))
    await collect_and_check(runtime, request("b"))
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


async def test_a_call_tool_step_runs_the_tool_and_reports_its_result() -> None:
    tools = ScriptedToolExecutor({"repo.list_files": "README.md\nsrc/"})
    runtime = FakeRuntime(
        {"writer": [CallTool("repo.list_files", {"path": "."}), Message(text="ok"), USAGE]},
        tools=tools,
    )

    events = await collect_and_check(runtime, request())

    call, result = events[0], events[1]
    assert isinstance(call, ToolCall)
    assert (call.name, call.arguments) == ("repo.list_files", {"path": "."})
    assert result == ToolResult(call_id=call.call_id, output="README.md\nsrc/")
    assert tools.calls == [("repo.list_files", {"path": "."})]
    assert isinstance(events[-1], Completed)


async def test_tool_errors_and_exceptions_become_error_results() -> None:
    tools = ScriptedToolExecutor(
        {"soft": ToolOutput(text="no such dir", is_error=True), "boom": RuntimeError("down")}
    )
    runtime = FakeRuntime({"writer": [CallTool("soft"), CallTool("boom"), USAGE]}, tools=tools)

    events = await collect_and_check(runtime, request())

    results = [e for e in events if isinstance(e, ToolResult)]
    assert [(r.output, r.is_error) for r in results] == [
        ("no such dir", True),
        ("tool failed: down", True),
    ]


async def test_a_call_tool_step_without_an_executor_fails_the_run() -> None:
    runtime = FakeRuntime({"writer": [CallTool("repo.list_files"), USAGE]})

    events = await collect_and_check(runtime, request())

    assert events == [Failed(error="tools requested but no tool executor is set: repo.list_files")]


async def test_with_tools_an_unscripted_node_calls_its_requested_tools_first() -> None:
    tools = ScriptedToolExecutor({"repo.list_files": "README.md"})
    asking = request().model_copy(update={"tools": ["repo.list_files"]})

    events = await collect_and_check(FakeRuntime(tools=tools), asking)

    assert [e.type for e in events] == ["tool_call", "tool_result", "message", "usage", "completed"]
    assert tools.calls == [("repo.list_files", {})]


async def test_an_unscripted_node_calls_tools_with_their_schema_example() -> None:
    tools = ScriptedToolExecutor(
        {"repo.read_file": "1	x", "repo.list_files": "README.md"},
        examples={"repo.read_file": {"path": "pyproject.toml"}},
    )
    asking = request().model_copy(update={"tools": ["repo.read_file", "repo.list_files"]})

    events = await collect_and_check(FakeRuntime(tools=tools), asking)

    calls = [e for e in events if isinstance(e, ToolCall)]
    assert [(c.name, c.arguments) for c in calls] == [
        ("repo.read_file", {"path": "pyproject.toml"}),
        ("repo.list_files", {}),
    ]
    assert tools.calls == [("repo.read_file", {"path": "pyproject.toml"}), ("repo.list_files", {})]


async def test_without_tools_requested_tools_are_not_called() -> None:
    asking = request().model_copy(update={"tools": ["repo.list_files"]})

    events = await collect_and_check(FakeRuntime(), asking)

    assert [e.type for e in events] == ["message", "usage", "completed"]
