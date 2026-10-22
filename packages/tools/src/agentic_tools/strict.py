"""MCP tools built from functions, with strict arguments and an example call."""

from collections.abc import Callable
from typing import Any, cast

from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict


def strict_tool(
    fn: Callable[..., Any],
    example: dict[str, Any],
    *,
    name: str | None = None,
    structured: bool = False,
) -> Tool:
    """A tool whose input schema carries one example call. Unknown arguments are rejected rather
    than ignored, so a model's typo is reported back to it. With `structured`, the function
    returns a model, which the result carries as structured content (and as JSON text)."""
    tool = Tool.from_function(fn, name=name, structured_output=structured)
    base = tool.fn_metadata.arg_model
    strict = cast(
        type[ArgModelBase],
        type(base.__name__, (base,), {"model_config": ConfigDict(extra="forbid")}),
    )
    tool.fn_metadata = tool.fn_metadata.model_copy(update={"arg_model": strict})
    tool.parameters["additionalProperties"] = False
    tool.parameters["examples"] = [example]
    return tool
