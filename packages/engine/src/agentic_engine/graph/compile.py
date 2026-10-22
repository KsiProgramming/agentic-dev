"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent`, `tool`, `gate` and `sequence`: sequences are flattened depth first into one
linear chain of agent, tool and gate nodes, each named by its spec node id. A node that does not
complete ends the run. Each node writes `node_started`, its agent events (a tool node: one
`tool_call` and its `tool_result`, and `pr_opened` if it published a branch) and
`node_<status>` to the run's event log. A gate pauses the
run (a LangGraph interrupt, so it needs a checkpointer); the runner writes its `node_started`
when the run stops there, and the gate writes `gate_decided` and its end once it is continued.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import JsonValue

from agentic_engine.agent import AgentNodeResult, AgentNodeStatus, run_agent_node
from agentic_engine.events import (
    NODE_CANCELLED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_STARTED,
    PR_OPENED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.gate import run_gate_node
from agentic_engine.graph.checkpoint import Checkpointer
from agentic_engine.graph.state import RunState, RunUpdate
from agentic_engine.spec import (
    PUBLISH_TOOLS,
    AgentNode,
    GateNode,
    Node,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
)
from agentic_engine.tool import run_tool_node
from agentic_runtime import AgentEvent, AgentRuntime, ToolExecutor

type CompiledWorkflow = CompiledStateGraph[RunState]
type StepNode = AgentNode | ToolNode | GateNode


class CompileError(ValueError):
    """The spec uses something this compiler does not support yet."""


def step_nodes(root: Node) -> list[StepNode]:
    """The agent, tool and gate nodes under `root` in run order (depth first)."""
    steps: list[StepNode] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode() | ToolNode() | GateNode():
                steps.append(node)
            case SequenceNode():
                pass
            case _:
                raise CompileError(f"node type {node.type!r} at {path} is not supported yet")
    return steps


NODE_END: dict[AgentNodeStatus, str] = {
    "completed": NODE_COMPLETED,
    "failed": NODE_FAILED,
    "cancelled": NODE_CANCELLED,
}


def compile_workflow(
    spec: WorkflowSpec,
    runtime: AgentRuntime,
    log: RunEventLog | None = None,
    checkpointer: Checkpointer | None = None,
    tools: ToolExecutor | None = None,
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`, tool nodes call `tools`, and
    both write to `log`, if given. With `checkpointer`, the state is saved after each node, in
    the run's thread; a spec with a gate needs one, since a paused run continues from it."""
    if log is None:
        log = RunEventLog(uuid4(), NullEventSink())
    steps = step_nodes(spec.root)
    if checkpointer is None and (gate := next((n for n in steps if isinstance(n, GateNode)), None)):
        raise CompileError(f"gate {gate.id!r} needs a checkpointer to pause the run")
    builder = StateGraph(RunState)
    for node in steps:
        builder.add_node(node.id, _step(node, runtime, tools, log))
    builder.add_edge(START, steps[0].id)
    for node, following in zip(steps, [*steps[1:], None], strict=True):
        if following is None:
            builder.add_edge(node.id, END)
        else:
            builder.add_conditional_edges(
                node.id, _continue_if_completed(node.id, following.id), [following.id, END]
            )
    return builder.compile(checkpointer=checkpointer)


def _step(
    node: StepNode, runtime: AgentRuntime, tools: ToolExecutor | None, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    async def on_event(event: AgentEvent) -> None:
        await log.agent_event(node.id, event)

    async def run(input: str) -> AgentNodeResult:
        match node:
            case ToolNode():
                return await run_tool_node(node, tools, on_event)
            case GateNode():
                return await run_gate_node(node, input, log)
            case AgentNode():
                return await run_agent_node(node, runtime, input, on_event)

    async def step(state: RunState) -> RunUpdate:
        # A gate runs again from its start when the run continues; the runner logs its start.
        if not isinstance(node, GateNode):
            await log.emit(NODE_STARTED, node_id=node.id)
        try:
            result = await run(state["last_text"])
        except asyncio.CancelledError:
            await log.emit(NODE_CANCELLED, node_id=node.id)
            raise
        if (pull := _pull_request(node, result)) is not None:
            await log.emit(PR_OPENED, node_id=node.id, payload=pull)
        payload: dict[str, JsonValue] = {"error": result.error} if result.error else {}
        await log.emit(NODE_END[result.status], node_id=node.id, payload=payload)
        return {"last_text": result.text, "results": {node.id: result}, "order": [node.id]}

    return step


_PULL_REQUEST_FIELDS = ("url", "number", "head", "base", "commit")


def _pull_request(node: StepNode, result: AgentNodeResult) -> dict[str, JsonValue] | None:
    """The pull request a completed publishing tool node opened, if its result names one."""
    if not (isinstance(node, ToolNode) and node.tool in PUBLISH_TOOLS):
        return None
    if result.status != "completed" or not result.data or "url" not in result.data:
        return None
    return {k: result.data[k] for k in _PULL_REQUEST_FIELDS if k in result.data}


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return next_id if state["results"][node_id].status == "completed" else END

    return route
