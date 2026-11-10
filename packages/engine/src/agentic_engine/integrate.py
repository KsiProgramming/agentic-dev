"""An orchestrator's integration branch (6.3): its completed tasks' branches merged into one.

After each round of an orchestrator whose body writes, the engine asks a `BranchIntegrator` to
merge the branches of the tasks that completed, in plan order, into `agent/<run>/<orchestrator>`.
That branch is what a gate after the orchestrator shows and edits and what `github.openPR`
publishes. An orchestrator in a loop (6.9) keeps the one branch across iterations: from the
second, its tasks start from that branch (`start_tasks`), so they build on the work merged so
far. The worker implements it over the run's sandbox, so the engine never runs git.
"""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

MAX_CONFLICT_PATHS = 10
"""How many conflicting paths a task's error names; the rest are counted."""


class MergeRequest(BaseModel):
    """A task branch to merge: its writer `key` (`task_writer_key`) and its merge message."""

    model_config = ConfigDict(frozen=True)

    key: str
    message: str


class Integration(BaseModel):
    """What one integration did, by writer key: the sources it `merged` (now, or by an earlier
    call), those with nothing to merge (`empty`), and those that conflict with the ones merged
    before them, with the conflicting paths. `head` is the integration branch's tip."""

    model_config = ConfigDict(frozen=True)

    branch: str
    head: str
    merged: list[str] = Field(default_factory=list[str])
    empty: list[str] = Field(default_factory=list[str])
    conflicts: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])


class BranchIntegrator(Protocol):
    """Merges task branches into an orchestrator's integration branch."""

    async def integrate(self, orchestrator_id: str, sources: Sequence[MergeRequest]) -> Integration:
        """Merge `sources`, in order, into `orchestrator_id`'s integration branch (made from the
        run's base if it does not exist). A source already merged counts as merged and is not
        merged again. A conflicting source is left out and the ones after it are still merged.
        Raises `IntegrationError` if the branch cannot be built for another reason."""
        ...

    async def start_tasks(self, orchestrator_id: str, keys: Sequence[str]) -> None:
        """Start the branches of the task writers `keys` from `orchestrator_id`'s integration
        branch instead of the run's base (6.9), leaving a branch that exists as it is; nothing
        if the integration branch does not exist yet. Raises `IntegrationError` if git fails."""
        ...


class IntegrationError(Exception):
    """An integration branch cannot be built; the message says why."""


def conflict_error(paths: Sequence[str]) -> str:
    """A conflicting task's error: ``conflicts with earlier tasks on a.py, b.py``, at most
    `MAX_CONFLICT_PATHS` paths, then how many more."""
    shown = ", ".join(paths[:MAX_CONFLICT_PATHS])
    more = len(paths) - MAX_CONFLICT_PATHS
    if more > 0:
        shown += f" and {more} more"
    return f"conflicts with earlier tasks on {shown}" if paths else "conflicts with earlier tasks"
