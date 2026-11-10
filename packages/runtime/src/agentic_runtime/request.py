"""What the engine asks a runtime to run. Independent of the workflow spec models."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue

NonEmptyStr = Annotated[str, Field(min_length=1)]


class AgentRequest(BaseModel):
    """One agent turn.

    `input` is the data the agent works on (previous outputs, repo content). It is kept apart from
    `instructions` so it is never treated as instructions. `context` is what the platform says
    about the run, such as the repository it works on: written by the engine from the run's own
    settings, never from model or repo output.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: NonEmptyStr
    role: NonEmptyStr
    instructions: NonEmptyStr
    input: str = ""
    model: NonEmptyStr | None = Field(default=None, description="Unset means the provider default.")
    tools: list[str] = Field(default_factory=list[str])
    context: str = Field(default="", description="The run's context from the platform, if any.")
    output_schema: dict[str, JsonValue] | None = Field(
        default=None,
        description="The JSON Schema the answer must match, if the node is typed (4.2); its "
        "instructions already say so. The engine checks the answer; a fake runtime may fit its "
        "answer to it (6.8).",
    )
