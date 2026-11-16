from collections.abc import AsyncIterator, Mapping
from typing import Any, NamedTuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.base import SerializerProtocol

type ChannelVersions = dict[str, str | int | float]

class Checkpoint(TypedDict):
    v: int
    id: str
    ts: str
    channel_values: dict[str, Any]
    channel_versions: ChannelVersions
    versions_seen: dict[str, ChannelVersions]
    updated_channels: list[str] | None

class CheckpointMetadata(TypedDict, total=False):
    source: str
    step: int
    parents: dict[str, str]
    run_id: str

class CheckpointTuple(NamedTuple):
    config: RunnableConfig
    checkpoint: Checkpoint
    metadata: CheckpointMetadata
    parent_config: RunnableConfig | None = None
    pending_writes: list[tuple[str, str, Any]] | None = None

class BaseCheckpointSaver[V]:
    serde: SerializerProtocol
    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None: ...
    def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: Mapping[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]: ...
    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig: ...
