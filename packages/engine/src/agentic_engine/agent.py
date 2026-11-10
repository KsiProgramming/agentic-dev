"""Runs one `agent` node on an `AgentRuntime`. The LangGraph compiler (0.4) wraps this."""

import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_engine.artifacts import ArtifactRef
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
type OnAgentEvent = Callable[[AgentEvent], Awaitable[None]]


class AgentNodeResult(BaseModel):
    """What an agent node produced. `failed` and `cancelled` are results, not exceptions."""

    model_config = ConfigDict(frozen=True)

    status: AgentNodeStatus
    text: str
    usage: Usage | None
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    events: list[AgentEvent] = Field(default_factory=list[AgentEvent])
    error: str | None = None
    # A tool node's structured result, if its tool returned one, or a typed output (4.2).
    data: dict[str, JsonValue] | None = None
    # The run artifact the node wrote, if it has `writes` and completed (4.3).
    artifact: ArtifactRef | None = None


TOOL_INTENT_INSTRUCTION = (
    "When you call a tool, fill its `description` with why you make the call, in under 10 words "
    '(e.g. "Read the frontend config"). People following the run read it.'
)
"""Added to the instructions of an agent with tools, so the console can say why each call was
made. Every platform tool takes the optional `description` (`agentic_tools.strict`)."""

OUTPUT_SCHEMA_INSTRUCTION = (
    "End your answer with one JSON object that matches this JSON Schema, and write nothing after "
    "it. The next step reads only that object."
)
"""Added, with the schema after it, to the instructions of an agent with an `output_schema`
(4.2). The engine parses the answer and checks it (`agentic_engine.ports`)."""


class RunContext(BaseModel):
    """What the platform tells every agent of a run about it, after its instructions: the
    repository the run works on (`repo`, `owner/name` or its URL; `repo_url` if different).
    Written from the run's own settings, never from model or repo output, so an agent knows where
    it works even when its input is only the work before it, or empty."""

    model_config = ConfigDict(frozen=True)

    repo: str | None = None
    repo_url: str | None = None

    def text(self) -> str:
        """The context as the agent reads it; empty when there is nothing to say."""
        if not self.repo:
            return ""
        url = f" ({self.repo_url})" if self.repo_url and self.repo_url != self.repo else ""
        return (
            f"This run works on the repository `{self.repo}`{url}, cloned for the run. The "
            "`repo.*` tools you are given read it, and change it if you may write. Your input is "
            "the work the step before you produced (for the first step, what the person who "
            "started the run asked for), never the repository itself: read the repository with "
            "your tools."
        )


def to_request(
    node: AgentNode, input: str, route_as: str | None = None, context: str = ""
) -> AgentRequest:
    """The runtime request for `node` on `input`, with the run's `context` (`RunContext.text`).
    `route_as` replaces the node id the request (and so its tool calls) is known by: a writer
    working on an orchestrator's task (6.1) writes on that task's branch (`task_writer_key`)."""
    instructions = node.instructions
    if node.tools:
        instructions = f"{instructions}\n\n{TOOL_INTENT_INSTRUCTION}"
    if node.output_schema is not None:
        schema = json.dumps(node.output_schema, ensure_ascii=False)
        instructions = f"{instructions}\n\n{OUTPUT_SCHEMA_INSTRUCTION}\n\n{schema}"
    return AgentRequest(
        node_id=route_as or node.id,
        role=node.role,
        instructions=instructions,
        input=input,
        model=node.model,
        tools=list(node.tools),
        context=context,
    )


async def run_agent_node(
    node: AgentNode,
    runtime: AgentRuntime,
    input: str,
    on_event: OnAgentEvent | None = None,
    route_as: str | None = None,
    context: str = "",
) -> AgentNodeResult:
    """Run `node` to its terminal event and summarise the stream, with the run's `context`.

    `on_event` sees each event as it arrives, before the stream is checked. Raises
    `ContractViolation` if the runtime's stream breaks the contract. If the caller is cancelled
    while the run is in flight, the run is cancelled too.
    """
    run = runtime.start(to_request(node, input, route_as, context))
    events: list[AgentEvent] = []
    try:
        async for event in run:
            events.append(event)
            if on_event is not None:
                await on_event(event)
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
    return sum_usage(e for e in events if isinstance(e, Usage))


def sum_usage(usages: Iterable[Usage | None]) -> Usage | None:
    """Add up usage records; `None` entries are skipped, and no records gives `None`.

    `premium_requests` stays `None` unless at least one record sets it. `estimated_usd` is `None`
    if any record has no price, so a partial sum is never shown as the cost. `model` is kept
    only when every record has the same one.
    """
    present = [u for u in usages if u is not None]
    if not present:
        return None
    premium = [u.premium_requests for u in present if u.premium_requests is not None]
    usd = [u.estimated_usd for u in present]
    models = {u.model for u in present}
    return Usage(
        model=models.pop() if len(models) == 1 else None,
        input_tokens=sum(u.input_tokens for u in present),
        output_tokens=sum(u.output_tokens for u in present),
        cache_read_tokens=sum(u.cache_read_tokens for u in present),
        cache_write_tokens=sum(u.cache_write_tokens for u in present),
        premium_requests=sum(premium) if premium else None,
        estimated_usd=None if None in usd else round(sum(u for u in usd if u is not None), 8),
    )
