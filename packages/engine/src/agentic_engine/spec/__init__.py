"""Workflow spec models (v0: `agent`, `tool`, `gate` and `sequence`)."""

from agentic_engine.spec.models import (
    AgentNode,
    GateNode,
    Node,
    NodeId,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
    node_tools,
    writer_node_ids,
)

__all__ = [
    "AgentNode",
    "GateNode",
    "Node",
    "NodeId",
    "SequenceNode",
    "ToolNode",
    "WorkflowSpec",
    "iter_nodes",
    "node_tools",
    "parse_spec",
    "writer_node_ids",
]


def parse_spec(data: object) -> WorkflowSpec:
    """Validate a decoded JSON document as a workflow spec; raises `pydantic.ValidationError`."""
    return WorkflowSpec.model_validate(data)
