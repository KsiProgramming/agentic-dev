"""Compiles a workflow spec to a LangGraph graph.

v0 supports `agent` and `sequence`: sequences are flattened depth first into one linear chain of
agent nodes, each named by its spec node id. A node that does not complete ends the run.
"""

from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentic_engine.agent import run_agent_node
from agentic_engine.graph.state import RunState, RunUpdate
from agentic_engine.spec import AgentNode, Node, SequenceNode, WorkflowSpec, iter_nodes
from agentic_runtime import AgentRuntime

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


def compile_workflow(spec: WorkflowSpec, runtime: AgentRuntime) -> CompiledWorkflow:
    """Build the graph for `spec`. Agent nodes run on `runtime`."""
    agents = agent_nodes(spec.root)
    builder = StateGraph(RunState)
    for agent in agents:
        builder.add_node(agent.id, _agent_step(agent, runtime))
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
    node: AgentNode, runtime: AgentRuntime
) -> Callable[[RunState], Awaitable[RunUpdate]]:
    async def step(state: RunState) -> RunUpdate:
        result = await run_agent_node(node, runtime, state["last_text"])
        return {"last_text": result.text, "results": {node.id: result}, "order": [node.id]}

    return step


def _continue_if_completed(node_id: str, next_id: str) -> Callable[[RunState], str]:
    def route(state: RunState) -> str:
        return next_id if state["results"][node_id].status == "completed" else END

    return route
