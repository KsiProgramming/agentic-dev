"""Workflow spec models (v0: `agent` and `sequence`)."""

from agentic_engine.spec.models import (
    AgentNode,
    Node,
    NodeId,
    SequenceNode,
    WorkflowSpec,
    iter_nodes,
)

__all__ = [
    "AgentNode",
    "Node",
    "NodeId",
    "SequenceNode",
    "WorkflowSpec",
    "iter_nodes",
    "parse_spec",
]


def parse_spec(data: object) -> WorkflowSpec:
    """Validate a decoded JSON document as a workflow spec; raises `pydantic.ValidationError`."""
    return WorkflowSpec.model_validate(data)
