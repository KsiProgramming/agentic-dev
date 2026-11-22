"""The real connector's mapping, on stand-ins shaped like the SDK's events (no network)."""

from types import SimpleNamespace
from typing import Any

import pytest
from copilot.generated.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.tools import ToolInvocation, ToolResult

from agentic_runtime.copilot import (
    AssistantMessage,
    CopilotTool,
    ReasoningChunk,
    SessionError,
    SessionIdle,
    TextChunk,
    ToolReply,
    UsageReport,
)
from agentic_runtime.copilot_sdk import SdkConnector, permission_handler, sdk_tool, translate


def event(kind: str, **data: Any) -> Any:
    return SimpleNamespace(type=SimpleNamespace(value=kind), data=SimpleNamespace(**data))


def test_text_reasoning_and_messages() -> None:
    assert translate(event("assistant.message_delta", delta_content="hi")) == TextChunk("hi")
    assert translate(event("assistant.message_delta", delta_content="")) is None
    assert translate(event("assistant.reasoning_delta", delta_content="hm")) == ReasoningChunk("hm")
    assert translate(event("assistant.message", content="answer")) == AssistantMessage("answer")
    # a turn that only asks for tools has no text and must not replace the earlier answer
    assert translate(event("assistant.message", content="")) is None


def test_usage_takes_cache_tokens_out_of_the_input() -> None:
    usage = translate(
        event(
            "assistant.usage",
            model="gpt-5",
            input_tokens=1000,
            output_tokens=50,
            cache_read_tokens=700,
            cache_write_tokens=100,
        )
    )

    assert usage == UsageReport(
        model="gpt-5",
        input_tokens=200,
        output_tokens=50,
        cache_read_tokens=700,
        cache_write_tokens=100,
    )


def test_usage_with_missing_counts_is_zero() -> None:
    usage = translate(
        event(
            "assistant.usage",
            model=None,
            input_tokens=None,
            output_tokens=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
        )
    )

    assert usage == UsageReport(model=None, input_tokens=0, output_tokens=0)


def test_idle_error_and_the_events_a_run_ignores() -> None:
    assert translate(event("session.idle", aborted=True)) == SessionIdle(aborted=True)
    assert translate(event("session.idle", aborted=None)) == SessionIdle()
    assert translate(event("session.error", message="bad", status_code=401)) == SessionError(
        "bad", 401
    )
    assert translate(event("tool.execution_start", tool_name="x")) is None


def test_permissions_are_answered_by_the_platform() -> None:
    handle = permission_handler(lambda ask: ask.kind == "custom-tool" and ask.tool_name == "ok")

    allowed = handle(SimpleNamespace(kind="custom-tool", tool_name="ok"), {})
    denied_tool = handle(SimpleNamespace(kind="custom-tool", tool_name="other"), {})
    denied_shell = handle(SimpleNamespace(kind="shell"), {})

    assert isinstance(allowed, PermissionDecisionApproveOnce)
    assert isinstance(denied_tool, PermissionDecisionReject)
    assert isinstance(denied_shell, PermissionDecisionReject)


async def test_a_platform_tool_becomes_an_sdk_tool_that_calls_its_handler() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def handler(call_id: str, arguments: dict[str, Any]) -> ToolReply:
        calls.append((call_id, arguments))
        return ToolReply("bad input", is_error=True) if arguments.get("bad") else ToolReply("fine")

    tool = sdk_tool(
        CopilotTool(
            name="repo__read_file",
            description="Read",
            parameters={"type": "object"},
            handler=handler,
        )
    )

    assert (tool.name, tool.description, tool.parameters) == (
        "repo__read_file",
        "Read",
        {"type": "object"},
    )
    call: Any = tool.handler  # the SDK's handler type is "sync or async"; ours is async
    ok: ToolResult = await call(ToolInvocation(tool_call_id="c1", arguments={"path": "a"}))
    bad: ToolResult = await call(ToolInvocation(tool_call_id="c2", arguments={"bad": True}))
    assert (ok.text_result_for_llm, ok.result_type) == ("fine", "success")
    assert (bad.text_result_for_llm, bad.result_type, bad.error) == (
        "bad input",
        "failure",
        "bad input",
    )
    assert calls == [("c1", {"path": "a"}), ("c2", {"bad": True})]


def test_the_connector_never_shows_its_token() -> None:
    token = "gho_SECRETSECRETSECRET1234"
    connector = SdkConnector(token)

    assert token not in repr(connector)
    assert token not in str(connector)
    with pytest.raises(ValueError, match="token is required"):
        SdkConnector("")


def test_usage_carries_the_calls_ai_credits_in_nano_units() -> None:
    usage = translate(
        event(
            "assistant.usage",
            model="gpt-5",
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=0,
            cache_write_tokens=0,
            copilot_usage=SimpleNamespace(total_nano_aiu=1_260_000_000),
        )
    )

    assert isinstance(usage, UsageReport)
    assert usage.nano_aiu == 1_260_000_000


def test_usage_without_copilot_usage_has_no_credits() -> None:
    counts = {"model": "m", "input_tokens": 1, "output_tokens": 1}
    counts |= {"cache_read_tokens": 0, "cache_write_tokens": 0}
    bare = translate(event("assistant.usage", **counts))
    empty = translate(
        event(
            "assistant.usage",
            **counts,
            copilot_usage=SimpleNamespace(total_nano_aiu=None),
        )
    )

    assert isinstance(bare, UsageReport)
    assert isinstance(empty, UsageReport)
    assert (bare.nano_aiu, empty.nano_aiu) == (None, None)
