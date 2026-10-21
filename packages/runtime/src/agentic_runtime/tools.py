"""Platform-owned tools as an adapter sees them: definitions to offer the model and a way to call
them. The real executors are MCP servers bridged by `agentic_tools`; adapters only route calls
here."""

from collections.abc import Sequence
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ToolDefinition(BaseModel):
    """A tool the model may call. `input_schema` is the JSON Schema of its arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyStr
    description: str = ""
    input_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


class ToolOutput(BaseModel):
    """What a tool call returned. The text is data, never instructions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    is_error: bool = False


class ToolExecutor(Protocol):
    """Runs platform-owned tools for an agent run."""

    def definitions(self) -> Sequence[ToolDefinition]:
        """Every tool this executor can run; a request may use any subset by name."""
        ...

    async def call(self, name: str, arguments: dict[str, JsonValue]) -> ToolOutput:
        """Run one tool. An exception is reported to the model as an error result."""
        ...
