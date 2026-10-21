"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent` and `sequence`: sequences are flattened depth first into one linear chain of
agent nodes, each named by its spec node id. A node that does not complete ends the run. Each node
writes `node_started`, its agent events and `node_<status>` to the run's event log.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import JsonValue

from agentic_engine.agent import AgentNodeStatus, run_agent_node
from agentic_engine.events import (
    NODE_CANCELLED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_STARTED,
    NullEventSink,
    RunEventLog,
)
from agentic_engine.graph.state import RunState, RunUpdate
from agentic_engine.spec import AgentNode, Node, SequenceNode, WorkflowSpec, iter_nodes
from agentic_runtime import AgentEvent, AgentRuntime

type CompiledWorkflow = CompiledStateGraph[RunState]


class CompileError(ValueError):
    """The spec uses something this compiler does not support yet."""


def agent_nodes(root: Node) -> list[AgentNode]:
    """The agent nodes under `root` in run order (depth first)."""
    agents: list[AgentNode] = []
    for path, node in iter_nodes(root):
        match node:
            case AgentNode():
                agents.append(node)
            case SequenceNode():
                pass
            case _:
                raise CompileError(f"node type {node.type!r} at {path} is not supported yet")
    return agents


NODE_END: dict[AgentNodeStatus, str] = {
    "completed": NODE_COMPLETED,
    "failed": NODE_FAILED,
    "cancelled": NODE_CANCELLED,
}


def compile_workflow(
    spec: WorkflowSpec, runtime: AgentRuntime, log: RunEventLog | None = None
) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime` and write to `log`, if given."""
    if log is None:
        log = RunEventLog(uuid4(), NullEventSink())
    agents = agent_nodes(spec.root)
    builder = StateGraph(RunState)
    for agent in agents:
        builder.add_node(agent.id, _agent_step(agent, runtime, log))
    builder.add_edge(START, agents[0].id)
    for agent, following in zip(agents, [*agents[1:], None], strict=True):
        if following is None:
            builder.add_edge(agent.id, END)
        else:
            builder.add_conditional_edges(
                agent.id, _continue_if_completed(agent.id, following.id), [following.id, END]
            )
    return builder.compile()


def _agent_step(
    node: AgentNode, runtime: AgentRuntime, log: RunEventLog
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    async def on_event(event: AgentEvent) -> None:
        await log.agent_event(node.id, event)

    async def step(state: RunState) -> RunUpdate:
        await log.emit(NODE_STARTED, node_id=node.id)
        try:
            result = await run_agent_node(node, runtime, state["last_text"], on_event)
        except asyncio.CancelledError:
            await log.emit(NODE_CANCELLED, node_id=node.id)
            raise
        payload: dict[str, JsonValue] = {"error": result.error} if result.error else {}
        await log.emit(NODE_END[result.status], node_id=node.id, payload=payload)
        return {"last_text": result.text, "results": {node.id: result}, "order": [node.id]}

    return step


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return next_id if state["results"][node_id].status == "completed" else END

    return route
