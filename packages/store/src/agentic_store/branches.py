"""Writers' commits saved outside the sandbox (12.2).

A run's first clone records its commit (`runs.base_sha`); later sandboxes are cloned there. Each
writer's branch and each integration branch is saved as a git bundle when a step completes, a
new version only when its tip moved (`run_branches`, append only), and the latest version of each
is fetched into a fresh sandbox (`latest_branches`).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_sandbox import COMMIT_ID, MAX_TAKE_FILE_BYTES, BranchBundle
from agentic_store.models import Run, RunBranch

type BranchKind = Literal["writer", "integration"]


class BundleTooLargeError(ValueError):
    """A branch's bundle is over `MAX_TAKE_FILE_BYTES`, so it is not saved."""


class SavedBranch(BaseModel):
    """One saved version of a branch, without its bundle."""

    model_config = ConfigDict(frozen=True)

    branch: str
    node_key: str
    kind: BranchKind
    version: int
    base_sha: str
    head_sha: str
    commits: int
    size: int
    created_at: datetime


async def record_base_sha(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, sha: str
) -> str:
    """Record `sha` as the commit the run's clone is at, unless one is recorded already; returns
    the run's base commit either way. Raises `ValueError` for a `sha` that is not a commit id."""
    if not COMMIT_ID.match(sha):
        raise ValueError(f"not a commit id: {sha!r}")
    async with sessions.begin() as session:
        await session.execute(
            update(Run).where(Run.id == run_id, Run.base_sha.is_(None)).values(base_sha=sha)
        )
        recorded = await session.scalar(select(Run.base_sha).where(Run.id == run_id))
    if recorded is None:
        raise ValueError(f"no run {run_id}")
    return recorded


async def save_branch(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    node_key: str,
    kind: BranchKind,
    bundle: BranchBundle,
) -> SavedBranch | None:
    """Save `bundle` as the next version of its branch, or nothing (`None`) if the latest saved
    version has the same tip. Raises `BundleTooLargeError` over `MAX_TAKE_FILE_BYTES`."""
    if len(bundle.data) > MAX_TAKE_FILE_BYTES:
        raise BundleTooLargeError(
            f"the branch's bundle is {len(bundle.data)} bytes, over the "
            f"{MAX_TAKE_FILE_BYTES // (1024 * 1024)} MB that can be saved"
        )
    async with sessions.begin() as session:
        latest = await session.execute(
            select(RunBranch.version, RunBranch.head_sha)
            .where(RunBranch.run_id == run_id, RunBranch.branch == bundle.branch)
            .order_by(RunBranch.version.desc())
            .limit(1)
            .with_for_update()
        )
        last = latest.first()
        if last is not None and last.head_sha == bundle.head_sha:
            return None
        row = RunBranch(
            run_id=run_id,
            branch=bundle.branch,
            version=(last.version if last is not None else 0) + 1,
            node_key=node_key,
            kind=kind,
            base_sha=bundle.base_sha,
            head_sha=bundle.head_sha,
            commits=bundle.commits,
            size=len(bundle.data),
            data=bundle.data,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row, ["created_at"])
        return _saved(row)


async def latest_branches(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[BranchBundle]:
    """The latest saved version of each of the run's branches, with its bundle, by branch."""
    async with sessions() as session:
        rows = await session.scalars(_latest(run_id))
        return [
            BranchBundle(
                branch=r.branch,
                base_sha=r.base_sha,
                data=r.data,
                head_sha=r.head_sha,
                commits=r.commits,
            )
            for r in rows
        ]


async def list_saved_branches(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[SavedBranch]:
    """The latest saved version of each of the run's branches, without bundles, by branch."""
    async with sessions() as session:
        return [_saved(r) for r in await session.scalars(_latest(run_id))]


def _latest(run_id: UUID) -> Select[RunBranch]:
    newest = (
        select(RunBranch.branch, func.max(RunBranch.version).label("version"))
        .where(RunBranch.run_id == run_id)
        .group_by(RunBranch.branch)
        .subquery()
    )
    return (
        select(RunBranch)
        .join(
            newest,
            (RunBranch.branch == newest.c.branch) & (RunBranch.version == newest.c.version),
        )
        .where(RunBranch.run_id == run_id)
        .order_by(RunBranch.branch)
    )


def _saved(row: RunBranch) -> SavedBranch:
    return SavedBranch(
        branch=row.branch,
        node_key=row.node_key,
        kind="integration" if row.kind == "integration" else "writer",
        version=row.version,
        base_sha=row.base_sha,
        head_sha=row.head_sha,
        commits=row.commits,
        size=row.size,
        created_at=row.created_at,
    )
