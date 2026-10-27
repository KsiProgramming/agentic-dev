"""MCP tools built from functions, with strict arguments and an example call."""

import inspect
from collections.abc import Callable
from typing import Any, cast

from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict, Field

INTENT_ARG = "description"
"""The optional argument in which an agent says why it makes a call. The console shows it as the
call's title; the tool function never sees it."""

INTENT_MAX_LENGTH = 80

INTENT_HELP = (
    "Why you make this call, in under 10 words (e.g. 'Read the frontend config'). "
    "Shown to the people following the run."
)


def strict_tool(
    fn: Callable[..., Any],
    example: dict[str, Any],
    *,
    name: str | None = None,
    structured: bool = False,
) -> Tool:
    """A tool whose input schema carries one example call. Unknown arguments are rejected rather
    than ignored, so a model's typo is reported back to it. With `structured`, the function
    returns a model, which the result carries as structured content (and as JSON text).

    Unless `fn` has a `description` parameter of its own (`github.createRepo`), the tool also
    takes an optional `description`: the caller's intent, dropped before `fn` runs."""
    tool = Tool.from_function(fn, name=name, structured_output=structured)
    base = tool.fn_metadata.arg_model
    namespace: dict[str, Any] = {"model_config": ConfigDict(extra="forbid")}
    with_intent = INTENT_ARG not in inspect.signature(fn).parameters
    if with_intent:
        namespace["__annotations__"] = {INTENT_ARG: str | None}
        namespace[INTENT_ARG] = Field(
            default=None, max_length=INTENT_MAX_LENGTH, description=INTENT_HELP
        )
        namespace["model_dump_one_level"] = _without_intent
    strict = cast(type[ArgModelBase], type(base.__name__, (base,), namespace))
    tool.fn_metadata = tool.fn_metadata.model_copy(update={"arg_model": strict})
    if with_intent:
        tool.parameters = strict.model_json_schema(by_alias=True)
    tool.parameters["additionalProperties"] = False
    tool.parameters["examples"] = [example]
    return tool


def _without_intent(self: ArgModelBase) -> dict[str, Any]:
    kwargs = ArgModelBase.model_dump_one_level(self)
    kwargs.pop(INTENT_ARG, None)
    return kwargs
