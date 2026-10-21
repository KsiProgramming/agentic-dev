"""Checks an event stream against the `AgentRuntime` contract (see `agentic_runtime.protocol`)."""

from collections.abc import Sequence

from agentic_runtime.events import AgentEvent, Completed, ToolCall, ToolResult, Usage, is_terminal


class ContractViolation(ValueError):
    """An event stream breaks the `AgentRuntime` contract. This is a bug in the runtime."""


def check_events(events: Sequence[AgentEvent]) -> None:
    """Raise `ContractViolation` unless `events` is a complete, valid stream."""
    calls: set[str] = set()
    results: set[str] = set()
    seen_usage = False
    for i, event in enumerate(events):
        if i > 0 and is_terminal(events[i - 1]):
            raise ContractViolation(f"event {i} ({event.type}) comes after the terminal event")
        match event:
            case ToolCall(call_id=call_id):
                if call_id in calls:
                    raise ContractViolation(f"event {i}: duplicate tool_call id {call_id!r}")
                calls.add(call_id)
            case ToolResult(call_id=call_id):
                if call_id not in calls:
                    raise ContractViolation(f"event {i}: tool_result {call_id!r} has no tool_call")
                if call_id in results:
                    raise ContractViolation(f"event {i}: second tool_result for {call_id!r}")
                results.add(call_id)
            case Usage():
                seen_usage = True
            case Completed() if not seen_usage:
                raise ContractViolation(f"event {i}: completed without a usage event before it")
            case _:
                pass
    if not events or not is_terminal(events[-1]):
        raise ContractViolation("stream does not end with a terminal event")
