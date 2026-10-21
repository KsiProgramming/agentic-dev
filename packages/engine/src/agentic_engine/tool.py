"""Runs one `tool` node: a single call of a platform tool with the spec's arguments, no model.
The LangGraph compiler wraps this, as it does `run_agent_node`."""

from agentic_engine.agent import AgentNodeResult, OnAgentEvent
from agentic_engine.spec import ToolNode
from agentic_runtime import ToolCall, ToolExecutor, ToolOutput, ToolResult


async def run_tool_node(
    node: ToolNode, tools: ToolExecutor | None, on_event: OnAgentEvent | None = None
) -> AgentNodeResult:
    """Call `node.tool` with `node.args` for this node, and report it as a `tool_call` and a
    `tool_result` event. The output (data, never instructions) is the node's text. An error
    result, an exception or a run without tools fails the node; it never raises."""
    call = ToolCall(call_id=f"{node.id}_call", name=node.tool, arguments=dict(node.args))
    if on_event is not None:
        await on_event(call)
    if tools is None:
        output = ToolOutput(text=f"no tools are available to this run: {node.tool}", is_error=True)
    else:
        try:
            output = await tools.call(node.tool, dict(node.args), node_id=node.id)
        except Exception as e:
            output = ToolOutput(text=f"tool failed: {type(e).__name__}", is_error=True)
    result = ToolResult(call_id=call.call_id, output=output.text, is_error=output.is_error)
    if on_event is not None:
        await on_event(result)
    return AgentNodeResult(
        status="failed" if output.is_error else "completed",
        text=output.text,
        usage=None,
        tool_calls=[call],
        events=[call, result],
        error=output.text if output.is_error else None,
    )
