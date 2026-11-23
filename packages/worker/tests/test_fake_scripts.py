"""The stack's test-only fake agent that repeats a failing call (13.7, e2e)."""

from agentic_runtime import AgentRequest, ToolCall, ToolOutput
from agentic_runtime.fake import FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor
from agentic_worker.fake_scripts import MISSING_PATH, REPEAT_FAILING_CALL, RepeatingFakeRuntime


def runtime() -> RepeatingFakeRuntime:
    tools = ScriptedToolExecutor({"repo.read_file": ToolOutput(text="no such file", is_error=True)})
    return RepeatingFakeRuntime(FakeRuntime(tools=tools), tools)


async def events_of(request: AgentRequest) -> list[str]:
    return [e.type async for e in runtime().start(request)]


async def test_an_agent_that_asks_for_it_reads_the_same_missing_file_again_and_again() -> None:
    request = AgentRequest(
        node_id="a", role="R", instructions=f"{REPEAT_FAILING_CALL} Read it.", input="go"
    )

    calls = [e async for e in runtime().start(request) if isinstance(e, ToolCall)]

    assert len(calls) == 30
    assert {c.arguments["path"] for c in calls} == {MISSING_PATH}


async def test_told_why_it_was_paused_the_agent_stops_and_answers() -> None:
    request = AgentRequest(
        node_id="a",
        role="R",
        instructions=f"{REPEAT_FAILING_CALL} Read it.",
        input="go",
        context="# Paused before\n\nA circuit breaker paused you.",
    )

    types = await events_of(request)

    assert "tool_call" not in types
    assert types[-1] == "completed" and "message" in types


async def test_any_other_agent_is_the_wrapped_runtimes() -> None:
    types = await events_of(AgentRequest(node_id="b", role="R", instructions="Say hi.", input="go"))

    assert types[-1] == "completed" and "tool_call" not in types
