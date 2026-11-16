"""Writers' commits saved outside the sandbox (12.2).

The code a writer commits lives in the run's sandbox until a gated `github.openPR` pushes it, so a
lost sandbox (a worker killed mid-run, a kept sandbox removed while a gate waits) would lose it,
although the checkpoint says its step completed. So when a step that may commit returns (an
agent, tool or gate step, a map item, a parallel branch, an orchestrator's task or its
`<id>.integrate`), and before its update is checkpointed, the engine asks a `BranchSaver` to save
every branch of the run whose tip moved since its last save. A crash can then never fall between
"step done" and "its commits saved". The worker implements it over the run's sandbox and
Postgres, and fetches the saved branches into the next fresh sandbox; the engine never runs git.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

type BranchKind = Literal["writer", "integration"]


class BranchSaved(BaseModel):
    """A branch saved as a new version: its writer `key` (a node id, `<orchestrator>.<task>`, or
    an orchestrator's id for its integration branch), its tip and how many commits it has on top
    of the run's base, and the bundle's `size` in bytes."""

    model_config = ConfigDict(frozen=True)

    key: str
    branch: str
    kind: BranchKind
    version: int
    head: str
    commits: int
    size: int


class BranchSaveFailed(BaseModel):
    """A branch that could not be saved, and why (too large, git failed)."""

    model_config = ConfigDict(frozen=True)

    key: str
    branch: str
    error: str


class BranchSaves(BaseModel):
    """What one save did."""

    model_config = ConfigDict(frozen=True)

    saved: list[BranchSaved] = Field(default_factory=list[BranchSaved])
    failed: list[BranchSaveFailed] = Field(default_factory=list[BranchSaveFailed])


class BranchSaver(Protocol):
    """Saves a run's branches outside its sandbox."""

    async def save(self, *, step: str | None = None) -> BranchSaves:
        """Save every writer and integration branch of the run whose tip moved since it was
        last saved, recording `step`, the top-level step the save ran in (12.4: a rerun from a
        step restores the versions saved before it). A branch that cannot be saved is reported
        in `failed` and not tried again at the same tip; nothing raises."""
        ...


def owner_node(key: str) -> str:
    """The spec node a writer key belongs to: a task writer's (`<orchestrator>.<task>`) is its
    orchestrator."""
    return key.split(".", 1)[0]
