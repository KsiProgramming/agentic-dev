"""`RunTools`: every tool executor of one run (`repo.*`, `github.*`) as a single `ToolExecutor`."""

from collections.abc import Sequence

from pydantic import JsonValue

from agentic_runtime.tools import ToolDefinition, ToolExecutor, ToolOutput


class RunTools:
    """Offers the tools of all `executors`; each call goes to the one offering that tool, with
    its `node_id`, so per-node routing (writers' worktrees) still applies."""

    def __init__(self, executors: Sequence[ToolExecutor]) -> None:
        self._definitions: list[ToolDefinition] = []
        self._owners: dict[str, ToolExecutor] = {}
        for executor in executors:
            for definition in executor.definitions():
                if definition.name in self._owners:
                    raise ValueError(f"two executors offer {definition.name}")
                self._owners[definition.name] = executor
                self._definitions.append(definition)

    def definitions(self) -> Sequence[ToolDefinition]:
        return self._definitions

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        owner = self._owners.get(name)
        if owner is None:
            return ToolOutput(text=f"unknown tool: {name}", is_error=True)
        return await owner.call(name, arguments, node_id=node_id)
