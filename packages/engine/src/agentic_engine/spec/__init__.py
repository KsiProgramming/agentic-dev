"""Workflow spec models (v0: `agent`, `tool`, `gate`, `sequence` and `loop`)."""

from agentic_engine.spec.models import (
    MAX_LOOP_ITERATIONS,
    PUBLISH_TOOLS,
    WRITE_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    Node,
    NodeId,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
    loop_errors,
    node_tools,
    publish_gate_errors,
    writer_node_ids,
)

__all__ = [
    "MAX_LOOP_ITERATIONS",
    "PUBLISH_TOOLS",
    "WRITE_TOOLS",
    "AgentNode",
    "GateNode",
    "LoopNode",
    "Node",
    "NodeId",
    "SequenceNode",
    "ToolNode",
    "WorkflowSpec",
    "iter_nodes",
    "loop_errors",
    "node_tools",
    "parse_spec",
    "publish_gate_errors",
    "writer_node_ids",
]


def parse_spec(data: object) -> WorkflowSpec:
    """Validate a decoded JSON document as a workflow spec; raises `pydantic.ValidationError`."""
    return WorkflowSpec.model_validate(data)
