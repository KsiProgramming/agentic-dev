"""Workflow spec models (v0: `agent`, `tool`, `gate`, `sequence`, `loop`, `map` and `reduce`)."""

from agentic_engine.spec.models import (
    MAX_AGENTS_ALIVE,
    MAX_AGENTS_SPAWNED,
    MAX_LOOP_ITERATIONS,
    PUBLISH_TOOLS,
    WRITE_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    MapNode,
    Node,
    NodeId,
    ReduceAgent,
    ReduceNode,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
    loop_errors,
    map_errors,
    node_tools,
    publish_gate_errors,
    writer_node_ids,
)

__all__ = [
    "MAX_AGENTS_ALIVE",
    "MAX_AGENTS_SPAWNED",
    "MAX_LOOP_ITERATIONS",
    "PUBLISH_TOOLS",
    "WRITE_TOOLS",
    "AgentNode",
    "GateNode",
    "LoopNode",
    "MapNode",
    "Node",
    "NodeId",
    "ReduceAgent",
    "ReduceNode",
    "SequenceNode",
    "ToolNode",
    "WorkflowSpec",
    "iter_nodes",
    "loop_errors",
    "map_errors",
    "node_tools",
    "parse_spec",
    "publish_gate_errors",
    "writer_node_ids",
]


def parse_spec(data: object) -> WorkflowSpec:
    """Validate a decoded JSON document as a workflow spec; raises `pydantic.ValidationError`."""
    return WorkflowSpec.model_validate(data)
