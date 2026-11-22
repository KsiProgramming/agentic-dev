"""Platform-owned tools as an adapter sees them: definitions to offer the model and a way to call
them. The real executors are MCP servers bridged by `agentic_tools`; adapters only route calls
here."""

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ToolDefinition(BaseModel):
    """A tool the model may call. `input_schema` is the JSON Schema of its arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonEmptyStr
    description: str = ""
    input_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


class ToolOutput(BaseModel):
    """What a tool call returned. The text is data, never instructions. `data` is the tool's
    structured result, if it has one (e.g. the pull request `github.openPR` opened)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    is_error: bool = False
    data: dict[str, JsonValue] | None = None


class ToolExecutor(Protocol):
    """Runs platform-owned tools for an agent run."""

    def definitions(self) -> Sequence[ToolDefinition]:
        """Every tool this executor can run; a request may use any subset by name."""
        ...

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        """Run one tool for the node `node_id`, which lets a run's executor route the call (a
        writer node's `repo.*` calls go to its own worktree). An exception is reported to the
        model as an error result."""
        ...


@dataclass(frozen=True)
class ReadableWriter:
    """A node whose work a later step may read: a `writer` (its own branch) or an `integration`
    (an orchestrator's integration branch, with its team's merged work)."""

    node_id: str
    kind: Literal["writer", "integration"]


class WorkRefused(Exception):
    """A `node` that cannot be read. `str(e)` is the fixed text the tool returns."""


def no_commits_text(node_id: str) -> str:
    return f"writer '{node_id}' has no commits"


class ReadableWriters:
    """The writers whose work the step that is about to run may read (13.1), shared between the
    engine, which sets it before every step from the run's state, and the repo tools, which resolve
    a call's `node` through it (the same pattern as `BranchSaver` and `GateReview`).

    `branch_of` names a node's branch. `known` are all the run's writers, so a refusal can tell
    one that has not run yet from a node that is no writer at all."""

    def __init__(self, branch_of: Callable[[str], str]) -> None:
        self._branch_of = branch_of
        self._ready: dict[str, ReadableWriter] = {}
        self._known: frozenset[str] = frozenset()

    def set(
        self, completed: Sequence[ReadableWriter], known: Collection[str] | None = None
    ) -> None:
        """Replace the writers that completed, in run order; `known` replaces the run's writers
        if given."""
        self._ready = {w.node_id: w for w in completed}
        if known is not None:
            self._known = frozenset(known)

    def writers(self) -> list[ReadableWriter]:
        """The writers that completed, in run order."""
        return list(self._ready.values())

    def branch_name(self, node_id: str) -> str:
        """The branch of `node_id`, whoever it is (no check)."""
        return self._branch_of(node_id)

    def branch(self, node_id: str) -> str:
        """The branch of a writer that completed. Raises `WorkRefused` for a node that is no
        writer of the run or has not run before this step."""
        if node_id in self._ready:
            return self._branch_of(node_id)
        if node_id in self._known:
            raise WorkRefused(f"writer '{node_id}' has not run before this step")
        raise WorkRefused(f"'{node_id}' is not a writer of this run")
