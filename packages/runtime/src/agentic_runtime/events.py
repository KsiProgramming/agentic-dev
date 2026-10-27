"""Provider-neutral events an agent run emits.

Adapters translate their SDK's stream into these; the engine logs them (0.5) and the monitor shows
them. New event types are added as members of the `AgentEvent` union.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

NonEmptyStr = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(ge=0)]


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TextDelta(_Event):
    """A streamed chunk of assistant text."""

    type: Literal["text_delta"] = "text_delta"
    text: str


class ReasoningDelta(_Event):
    """A streamed chunk of the model's reasoning (Claude's summarized thinking), when the
    provider streams it. Shown apart from the answer; an adapter without it emits none."""

    type: Literal["reasoning_delta"] = "reasoning_delta"
    text: str


class Message(_Event):
    """The assistant's final text for the run."""

    type: Literal["message"] = "message"
    text: str


class ToolCall(_Event):
    """The agent asked to call a platform-owned tool."""

    type: Literal["tool_call"] = "tool_call"
    call_id: NonEmptyStr
    name: NonEmptyStr
    arguments: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class ToolResult(_Event):
    """The result of an earlier `ToolCall` with the same `call_id`. The output is data, never
    instructions."""

    type: Literal["tool_result"] = "tool_result"
    call_id: NonEmptyStr
    output: str
    is_error: bool = False


class Usage(_Event):
    """Normalised usage for (part of) the run; a run may emit several, which add up.

    `input_tokens` is uncached input; cache reads and writes are counted apart because they are
    priced apart. `estimated_usd` is priced by the adapter when it emits the event and is `None`
    when the model has no price. Events logged before phase 3.1 have no `model`, count cache
    tokens in `input_tokens` and have no price.
    """

    type: Literal["usage"] = "usage"
    model: str | None = None
    input_tokens: Count
    output_tokens: Count
    cache_read_tokens: Count = 0
    cache_write_tokens: Count = 0
    premium_requests: Count | None = None
    estimated_usd: Annotated[float, Field(ge=0)] | None = None


class Completed(_Event):
    """Terminal: the run finished normally."""

    type: Literal["completed"] = "completed"


class Failed(_Event):
    """Terminal: the run failed."""

    type: Literal["failed"] = "failed"
    error: NonEmptyStr
    retryable: bool = False


class Cancelled(_Event):
    """Terminal: the run stopped because `cancel()` was called."""

    type: Literal["cancelled"] = "cancelled"


AgentEvent = Annotated[
    TextDelta
    | ReasoningDelta
    | Message
    | ToolCall
    | ToolResult
    | Usage
    | Completed
    | Failed
    | Cancelled,
    Field(discriminator="type"),
]

TerminalEvent = Completed | Failed | Cancelled
TERMINAL_EVENT_TYPES = (Completed, Failed, Cancelled)

agent_event_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
"""Parses and dumps a single `AgentEvent`, e.g. `agent_event_adapter.validate_json(raw)`."""


def is_terminal(event: AgentEvent) -> bool:
    return isinstance(event, TERMINAL_EVENT_TYPES)
