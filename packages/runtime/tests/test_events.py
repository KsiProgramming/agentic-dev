import pytest
from pydantic import ValidationError

from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    Cancelled,
    Completed,
    ContractViolation,
    Failed,
    Message,
    TextDelta,
    ToolCall,
    ToolResult,
    Usage,
    agent_event_adapter,
    check_events,
    is_terminal,
)

EXAMPLES: list[AgentEvent] = [
    TextDelta(text="Hel"),
    Message(text="Hello"),
    ToolCall(call_id="c1", name="repo.read_file", arguments={"path": "README.md", "n": [1, 2]}),
    ToolResult(call_id="c1", output="# Title", is_error=False),
    Usage(input_tokens=12, output_tokens=3, premium_requests=1, estimated_usd=0.0004),
    Usage(
        model="claude-opus-5-5",
        input_tokens=12,
        output_tokens=3,
        cache_read_tokens=400,
        cache_write_tokens=50,
        estimated_usd=0.00021,
    ),
    Completed(),
    Failed(error="rate limited", retryable=True),
    Cancelled(),
]


@pytest.mark.parametrize("event", EXAMPLES, ids=lambda e: e.type)
def test_event_round_trips_through_json(event: AgentEvent) -> None:
    raw = agent_event_adapter.dump_json(event)
    assert agent_event_adapter.validate_json(raw) == event


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        agent_event_adapter.validate_python({"type": "thinking", "text": "hm"})
    assert exc.value.errors()[0]["type"] == "union_tag_invalid"


def test_extra_keys_are_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        agent_event_adapter.validate_python({"type": "message", "text": "x", "txt": "y"})
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_negative_token_counts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Usage(input_tokens=-1, output_tokens=0)


def test_usage_logged_before_cache_fields_still_parses() -> None:
    event = agent_event_adapter.validate_python(
        {"type": "usage", "input_tokens": 12, "output_tokens": 3, "estimated_usd": None}
    )
    assert event == Usage(model=None, input_tokens=12, output_tokens=3, cache_read_tokens=0)


def test_terminal_events() -> None:
    assert [e.type for e in EXAMPLES if is_terminal(e)] == ["completed", "failed", "cancelled"]


def test_request_rejects_extra_keys_and_empty_instructions() -> None:
    with pytest.raises(ValidationError):
        AgentRequest.model_validate({"node_id": "a", "role": "r", "instructions": ""})
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(
            {"node_id": "a", "role": "r", "instructions": "i", "temprature": 1}
        )


USAGE = Usage(input_tokens=1, output_tokens=1)
CALL = ToolCall(call_id="c1", name="t")
RESULT = ToolResult(call_id="c1", output="ok")


@pytest.mark.parametrize(
    "events",
    [
        [Message(text="hi"), USAGE, Completed()],
        [CALL, RESULT, USAGE, Message(text="hi"), Completed()],
        [Failed(error="boom")],
        [TextDelta(text="h"), Cancelled()],
    ],
)
def test_valid_streams_pass_the_contract(events: list[AgentEvent]) -> None:
    check_events(events)


@pytest.mark.parametrize(
    ("events", "msg"),
    [
        ([], "does not end with a terminal event"),
        ([Message(text="hi"), USAGE], "does not end with a terminal event"),
        ([USAGE, Completed(), Message(text="late")], "after the terminal event"),
        ([USAGE, Completed(), Cancelled()], "after the terminal event"),
        ([Message(text="hi"), Completed()], "without a usage event"),
        ([RESULT, USAGE, Completed()], "has no tool_call"),
        ([CALL, CALL, USAGE, Completed()], "duplicate tool_call id"),
        ([CALL, RESULT, RESULT, USAGE, Completed()], "second tool_result"),
    ],
)
def test_invalid_streams_break_the_contract(events: list[AgentEvent], msg: str) -> None:
    with pytest.raises(ContractViolation, match=msg):
        check_events(events)
