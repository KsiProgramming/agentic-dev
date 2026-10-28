"""Checkpointing a run's graph state, so another worker can resume it after the last completed
node (AC-8). The engine takes any LangGraph `BaseCheckpointSaver`: tests use `InMemorySaver`,
workers the Postgres saver from `agentic_store`. Both serialise with `checkpoint_serde()`.
"""

from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

type Checkpointer = BaseCheckpointSaver[str]

CHECKPOINT_TYPES: tuple[tuple[str, str], ...] = (
    ("agentic_engine.agent", "AgentNodeResult"),
    ("agentic_engine.artifacts", "ArtifactRef"),
    ("agentic_runtime.events", "Usage"),
)
"""The classes `RunState` holds, which a checkpoint may deserialise. LangGraph blocks any other."""


def checkpoint_serde() -> JsonPlusSerializer:
    """The serializer for run checkpoints, allowing only `CHECKPOINT_TYPES`."""
    return JsonPlusSerializer(allowed_msgpack_modules=list(CHECKPOINT_TYPES))


def thread_config(run_id: UUID) -> RunnableConfig:
    """A run's checkpoints live in the LangGraph thread named by its run id."""
    return {"configurable": {"thread_id": str(run_id)}}
