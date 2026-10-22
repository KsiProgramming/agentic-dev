from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Self

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, StateSnapshot

class DrawableGraph:
    nodes: Mapping[str, object]

class CompiledStateGraph[StateT]:
    checkpointer: BaseCheckpointSaver[str] | None
    async def ainvoke(
        self, input: StateT | Command[Any] | None, config: RunnableConfig | None = None
    ) -> StateT: ...
    async def aget_state(self, config: RunnableConfig) -> StateSnapshot: ...
    def get_graph(self) -> DrawableGraph: ...

class StateGraph[StateT]:
    def __init__(self, state_schema: type[StateT]) -> None: ...
    def add_node(
        self, node: str, action: Callable[[StateT], Awaitable[Mapping[str, object]]]
    ) -> Self: ...
    def add_edge(self, start_key: str, end_key: str) -> Self: ...
    def add_conditional_edges(
        self, source: str, path: Callable[[StateT], str], path_map: Sequence[str] | None = None
    ) -> Self: ...
    def compile(
        self, checkpointer: BaseCheckpointSaver[str] | None = None
    ) -> CompiledStateGraph[StateT]: ...
