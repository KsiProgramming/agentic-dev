"""Runs one `agent` node on an `AgentRuntime`. The LangGraph compiler (0.4) wraps this."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentic_engine.spec import AgentNode
from agentic_runtime import (
    AgentEvent,
    AgentRequest,
    AgentRuntime,
    Cancelled,
    Failed,
    Message,
    TextDelta,
    ToolCall,
    Usage,
    check_events,
    is_terminal,
)

type AgentNodeStatus = Literal["completed", "failed", "cancelled"]


class AgentNodeResult(BaseModel):
    """What an agent node produced. `failed` and `cancelled` are results, not exceptions."""

    model_config = ConfigDict(frozen=True)

    status: AgentNodeStatus
    text: str
    usage: Usage | None
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    events: list[AgentEvent] = Field(default_factory=list[AgentEvent])
    error: str | None = None


def to_request(node: AgentNode, input: str) -> AgentRequest:
    return AgentRequest(
        node_id=node.id,
        role=node.role,
        instructions=node.instructions,
        input=input,
        model=node.model,
        tools=list(node.tools),
    )


async def run_agent_node(node: AgentNode, runtime: AgentRuntime, input: str) -> AgentNodeResult:
    """Run `node` to its terminal event and summarise the stream.

    Raises `ContractViolation` if the runtime's stream breaks the contract. If the caller is
    cancelled while the run is in flight, the run is cancelled too.
    """
    run = runtime.start(to_request(node, input))
    events: list[AgentEvent] = []
    try:
        async for event in run:
            events.append(event)
    finally:
        if not events or not is_terminal(events[-1]):
            run.cancel()
    check_events(events)

    status: AgentNodeStatus
    error: str | None = None
    match events[-1]:
        case Failed(error=message):
            status, error = "failed", message
        case Cancelled():
            status = "cancelled"
        case _:
            status = "completed"
    return AgentNodeResult(
        status=status,
        text=_final_text(events),
        usage=_total_usage(events),
        tool_calls=[e for e in events if isinstance(e, ToolCall)],
        events=events,
        error=error,
    )


def _final_text(events: Sequence[AgentEvent]) -> str:
    """The last `message`, or the streamed deltas if the runtime sent no `message`."""
    messages = [e.text for e in events if isinstance(e, Message)]
    if messages:
        return messages[-1]
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def _total_usage(events: Sequence[AgentEvent]) -> Usage | None:
    usages = [e for e in events if isinstance(e, Usage)]
    if not usages:
        return None
    premium = [u.premium_requests for u in usages if u.premium_requests is not None]
    usd = [u.estimated_usd for u in usages if u.estimated_usd is not None]
    return Usage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        premium_requests=sum(premium) if premium else None,
        estimated_usd=sum(usd) if usd else None,
    )
