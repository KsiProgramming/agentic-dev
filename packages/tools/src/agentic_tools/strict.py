"""MCP tools built from functions, with strict arguments and an example call."""

import inspect
from collections.abc import Callable
from typing import Any, cast

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase
from pydantic import ConfigDict, Field

from agentic_runtime.plans import ENGINE_ONLY_ARGS, STALE_PREFIX, WritePlan

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
    plannable: bool = False,
) -> Tool:
    """A tool whose input schema carries one example call. Unknown arguments are rejected rather
    than ignored, so a model's typo is reported back to it. With `structured`, the function
    returns a model, which the result carries as structured content (and as JSON text).

    Unless `fn` has a `description` parameter of its own (`github.createRepo`), the tool also
    takes an optional `description`: the caller's intent, dropped before `fn` runs.

    A `plannable` tool (an outward write, 13.8) has the engine-only parameters `plan` and `expect`
    and returns a `WritePlan` in plan mode. They are accepted but not advertised, so no manifest
    shows them; every other tool refuses them as unknown arguments."""
    declared = ENGINE_ONLY_ARGS & set(inspect.signature(fn).parameters)
    if declared != (ENGINE_ONLY_ARGS if plannable else set()):
        raise TypeError(f"{fn.__name__}: `plan` and `expect` belong to plannable tools only")
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
    if plannable:
        for hidden in ENGINE_ONLY_ARGS:
            tool.parameters.get("properties", {}).pop(hidden, None)
            required = cast(list[str], tool.parameters.get("required", []))
            tool.parameters["required"] = [r for r in required if r != hidden]
        _publish_plan_result(tool)
    tool.parameters["additionalProperties"] = False
    tool.parameters["examples"] = [example]
    return tool


def _publish_plan_result(tool: Tool) -> None:
    """The tool's structured result is its own model, or a `WritePlan` in plan mode."""
    meta = tool.fn_metadata
    if meta.output_model is None:
        raise TypeError(f"{tool.name}: a plannable tool returns a model")
    both = meta.output_model | WritePlan
    updated = meta.model_copy(update={"output_model": both, "output_schema": None})
    updated.model_post_init(None)
    tool.fn_metadata = updated


def _without_intent(self: ArgModelBase) -> dict[str, Any]:
    kwargs = ArgModelBase.model_dump_one_level(self)
    kwargs.pop(INTENT_ARG, None)
    return kwargs


def stale(what: str) -> ToolError:
    """A write refused because what it was planned against changed (13.8)."""
    return ToolError(f"{STALE_PREFIX}: {what}")


def planned(plan: WritePlan) -> Any:
    """`plan` as a plannable tool's return value: in plan mode a tool answers with a `WritePlan`
    where its signature says its own result (`strict_tool(plannable=True)` publishes both)."""
    return plan
