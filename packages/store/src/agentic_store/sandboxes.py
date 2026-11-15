"""Kept sandboxes and saved commits of runs that did not succeed (12.3).

A failed or cancelled run's sandbox is kept for its policy's `sandbox_ttl_s`: the worker that
ends it adds `sandbox_kept_until` to its end event, which the event sink copies to the run
(`runs.sandbox_kept_until`). Every worker's sweep removes the sandboxes past it
(`remove_expired_sandboxes`), and drops the bundles of finished runs past their
`branch_retention_days` (`drop_old_bundles`), keeping the versions' changed files. A user may
ask for a kept sandbox to go now (`request_sandbox_removal`): the next sweep removes it. Only
workers touch sandboxes; the API only moves the date.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.policy import BRANCH_RETENTION_DAYS
from agentic_store.approvals import RunNotFoundError
from agentic_store.audit import audit
from agentic_store.models import Run, RunBranch

type SandboxState = Literal["none", "running", "kept", "removed"]


class SandboxNotKeptError(Exception):
    """The run has no kept sandbox to remove: it is still running, never kept one, or it is
    removed already."""


class SandboxInfo(BaseModel):
    """What happened to a run's sandbox: `none` (no sandbox, or a run that succeeded, whose
    sandbox went when it ended), `running` (the run has not ended), `kept` until `kept_until`, or
    `removed` at `removed_at`."""

    model_config = ConfigDict(frozen=True)

    state: SandboxState
    kept_until: datetime | None = None
    removed_at: datetime | None = None


def sandbox_info(
    status: str,
    kept_until: datetime | None,
    removed_at: datetime | None,
    *,
    has_repo: bool = True,
) -> SandboxInfo:
    """The `SandboxInfo` of a run from its status and its sandbox columns; a run with no repo
    never has a sandbox."""
    if not has_repo:
        return SandboxInfo(state="none")
    if removed_at is not None:
        return SandboxInfo(state="removed", kept_until=kept_until, removed_at=removed_at)
    if kept_until is not None:
        return SandboxInfo(state="kept", kept_until=kept_until)
    if status in ("queued", "running", "waiting"):
        return SandboxInfo(state="running")
    return SandboxInfo(state="none")


async def kept_sandbox_run_ids(sessions: async_sessionmaker[AsyncSession]) -> set[UUID]:
    """Runs whose sandbox is kept and not removed yet: a worker's startup sweep spares them."""
    async with sessions() as session:
        rows = await session.scalars(
            select(Run.id).where(
                Run.sandbox_kept_until.is_not(None), Run.sandbox_removed_at.is_(None)
            )
        )
        return set(rows)


async def remove_expired_sandboxes(
    sessions: async_sessionmaker[AsyncSession], remove: Callable[[UUID], Awaitable[None]]
) -> list[UUID]:
    """Remove, one at a time, each kept sandbox past its `sandbox_kept_until`: lock the run
    (`SKIP LOCKED`, so workers share the sweep), `remove` it, then mark it removed with a
    `sandbox.removed` audit entry, in that transaction. A run whose `remove` raises is left for
    the next sweep. Returns the runs whose sandbox was removed."""
    removed: list[UUID] = []
    failed: set[UUID] = set()
    while True:
        try:
            async with sessions.begin() as session:
                query = (
                    select(Run)
                    .where(
                        Run.sandbox_kept_until <= func.now(),
                        Run.sandbox_removed_at.is_(None),
                        Run.id.not_in(failed),
                    )
                    .order_by(Run.sandbox_kept_until)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                run = await session.scalar(query)
                if run is None:
                    return removed
                run_id = run.id
                try:
                    await remove(run_id)
                except Exception as e:
                    raise _RemoveFailed(run_id) from e
                _mark_removed(session, run, await session.scalar(select(func.now())))
                removed.append(run_id)
        except _RemoveFailed as e:
            failed.add(e.run_id)


class _RemoveFailed(Exception):
    def __init__(self, run_id: UUID) -> None:
        super().__init__(f"could not remove the sandbox of run {run_id}")
        self.run_id = run_id


def _mark_removed(session: AsyncSession, run: Run, now: datetime | None) -> None:
    kept_until = run.sandbox_kept_until
    run.sandbox_removed_at = now
    audit(
        session,
        run.workspace_id,
        "sandbox.removed",
        actor_type="system",
        run_id=run.id,
        details={"kept_until": kept_until.isoformat() if kept_until is not None else None},
    )


async def request_sandbox_removal(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> SandboxInfo:
    """Ask for the run's kept sandbox to be removed now: its `sandbox_kept_until` becomes now, so
    the next sweep removes it, with a `sandbox.remove_requested` audit entry. Asking again before
    the sweep is harmless and adds no entry. Raises `RunNotFoundError`, or `SandboxNotKeptError`
    if the run has no kept sandbox."""
    async with sessions.begin() as session:
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise RunNotFoundError(f"run {run_id} not found")
        if run.sandbox_kept_until is None or run.sandbox_removed_at is not None:
            raise SandboxNotKeptError(f"run {run_id} has no kept sandbox")
        now = await session.scalar(select(func.now()))
        assert now is not None
        if run.sandbox_kept_until > now:
            audit(
                session,
                run.workspace_id,
                "sandbox.remove_requested",
                run_id=run.id,
                details={"kept_until": run.sandbox_kept_until.isoformat()},
            )
            run.sandbox_kept_until = now
        return sandbox_info(run.status, run.sandbox_kept_until, run.sandbox_removed_at)


async def drop_old_bundles(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Drop the bundles of runs that ended more than their policy's `branch_retention_days` ago
    (a run created before 12.3 gets the default), keeping each version's row and changes, and
    stamping `bundle_removed_at`. Returns how many versions lost their bundle."""
    days = func.coalesce(
        cast(Run.policy["branch_retention_days"].astext, Integer), BRANCH_RETENTION_DAYS
    )
    expired = (
        select(Run.id)
        .where(
            Run.finished_at.is_not(None),
            Run.finished_at + days * timedelta(days=1) <= func.now(),
        )
        .scalar_subquery()
    )
    async with sessions.begin() as session:
        result = await session.execute(
            update(RunBranch)
            .where(RunBranch.data.is_not(None), RunBranch.run_id.in_(expired))
            .values(data=None, bundle_removed_at=func.now())
            .execution_options(synchronize_session=False)
        )
    return int(getattr(result, "rowcount", 0) or 0)
