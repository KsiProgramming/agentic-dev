"""Writers' commits saved outside the sandbox (12.2).

A run's first clone records its commit (`runs.base_sha`); later sandboxes are cloned there. Each
writer's branch and each integration branch is saved as a git bundle when a step completes, a
new version only when its tip moved (`run_branches`, append only), and the latest version of each
is fetched into a fresh sandbox (`latest_branches`).

Each version also keeps the files it changed on top of the base, as a gate shows them (12.3), so
they are shown after the sandbox, and later the bundle, is gone (`saved_changes`). A run that
failed or was cancelled saves each writer's uncommitted work as a `wip` version of
`wip/<run>/<key>`, which is never restored.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import NODE_STARTED
from agentic_engine.gate import FileChange
from agentic_engine.spec import task_writer_orchestrator
from agentic_sandbox import COMMIT_ID, MAX_TAKE_FILE_BYTES, BranchBundle, branch_name
from agentic_store.models import Run, RunBranch, RunEventRow

type BranchKind = Literal["writer", "integration", "wip"]

_CHANGES = TypeAdapter(list[FileChange])
_KINDS: dict[str, BranchKind] = {"writer": "writer", "integration": "integration", "wip": "wip"}


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
    # When the bundle was dropped past the run's retention (12.3); its changes stay.
    bundle_removed_at: datetime | None = None


class SavedChanges(SavedBranch):
    """A saved version with the files it changed on top of its base (12.3): `changes`, or why
    they could not be read (`changes_error`); neither for a version saved before 12.3."""

    changes: list[FileChange] | None = None
    changes_error: str | None = None


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
    changes: list[FileChange] | None = None,
    changes_error: str | None = None,
    *,
    step: str | None = None,
) -> SavedBranch | None:
    """Save `bundle` as the next version of its branch, with the files it changed (`changes`,
    or `changes_error`) and the top-level step it was saved in (`step`, 12.4), or nothing
    (`None`) if the latest saved version has the same tip. Raises `BundleTooLargeError` over
    `MAX_TAKE_FILE_BYTES`."""
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
            changes=None if changes is None else _CHANGES.dump_python(changes, mode="json"),
            changes_error=changes_error,
            step=step,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row, ["created_at"])
        return _saved(row)


async def latest_branches(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[BranchBundle]:
    """The latest saved version of each of the run's writer and integration branches, with its
    bundle, by branch: what a fresh sandbox gets back. Uncommitted work (`wip`) is never restored,
    and a version whose bundle was dropped cannot be."""
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
            if r.kind != "wip" and r.data is not None
        ]


async def list_saved_branches(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[SavedBranch]:
    """The latest saved version of each of the run's branches, without bundles, by branch."""
    async with sessions() as session:
        return [_saved(r) for r in await session.scalars(_latest(run_id))]


async def saved_changes(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[SavedChanges]:
    """The latest saved version of each of the run's branches with the files it changed, by
    branch (12.3)."""
    async with sessions() as session:
        return [
            SavedChanges(
                **_saved(r).model_dump(),
                changes=None if r.changes is None else _CHANGES.validate_python(r.changes),
                changes_error=r.changes_error,
            )
            for r in await session.scalars(_latest(run_id))
        ]


class RerunBranchesError(ValueError):
    """The original run's saved code cannot be restored for a rerun from a step (12.4)."""


async def rerun_branches(
    sessions: async_sessionmaker[AsyncSession],
    source_run: UUID,
    target_run: UUID,
    before: Sequence[str],
    wip_step: str | None = None,
    *,
    with_data: bool = True,
    latest: bool = False,
) -> list[BranchBundle]:
    """The code of `source_run` as it was before a top-level step (12.4), for its rerun
    `target_run` to restore: the latest version of each writer and integration branch saved in
    the steps `before` it, and, with `wip_step`, each writer's uncommitted work saved when the
    run ended in that step in place of its branch (the `wip` bundle holds the branch's commits
    and one more with the work). Each comes under the new run's name (`agent/<target>/<key>`),
    fetched from the original's (`source`). Without `with_data` the bundles are left empty, to
    check a rerun can start before it is created.

    With `latest` (a follow-up of a pull request review, 7.6) it takes the latest saved version
    of each branch whatever step saved it, a gate's edits included: the code the pull request
    holds, not the code before the step. Task writers' branches are left out: the follow-up's
    tasks start from their orchestrator's integration branch, which holds their work.

    Raises `RerunBranchesError` when a version it needs was saved before 12.4 (no step to tell
    which versions it had), or its bundle was dropped past the run's retention (12.3)."""
    async with sessions() as session:
        columns = [c for c in RunBranch.__table__.columns if c.key != "data" or with_data]
        rows = (
            await session.execute(
                select(*columns, RunBranch.data.is_(None).label("dropped"))
                .where(RunBranch.run_id == source_run)
                .order_by(RunBranch.branch, RunBranch.version)
            )
        ).all()
    if not latest and any(r.step is None and r.kind != "wip" for r in rows):
        raise RerunBranchesError(
            "its code was saved before rerunning from a step existed; rerun it from the start"
        )
    chosen: dict[str, Any] = {}  # by node key: the version to restore
    for r in rows:
        if r.kind == "wip":
            continue
        if latest and task_writer_orchestrator(r.node_key) is None:
            chosen[r.node_key] = r  # rows come oldest first: the last one wins
        elif not latest and r.step in before:
            chosen[r.node_key] = r
    if wip_step is not None:
        for r in rows:
            if r.kind == "wip" and r.step == wip_step:
                chosen[r.node_key] = r
    bundles: list[BranchBundle] = []
    for key, r in sorted(chosen.items()):
        if r.dropped:
            raise RerunBranchesError(
                f"the saved code of {key} was removed after the run's retention"
            )
        bundles.append(
            BranchBundle(
                branch=branch_name(target_run, key),
                source=r.branch,
                base_sha=r.base_sha,
                data=r.data if with_data else b"",
                head_sha=r.head_sha,
                commits=r.commits,
            )
        )
    return bundles


async def has_uncommitted(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, step: str
) -> bool:
    """Whether the run saved uncommitted work (`wip`) when it ended in the top-level `step`."""
    async with sessions() as session:
        found = await session.scalar(
            select(RunBranch.branch)
            .where(RunBranch.run_id == run_id, RunBranch.kind == "wip", RunBranch.step == step)
            .limit(1)
        )
    return found is not None


async def last_started_step(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, steps: Collection[str]
) -> str | None:
    """The last of the top-level `steps` the run started (its latest `node_started` among
    them): the step a run that ended was in."""
    if not steps:
        return None
    async with sessions() as session:
        return await session.scalar(
            select(RunEventRow.node_id)
            .where(
                RunEventRow.run_id == run_id,
                RunEventRow.type == NODE_STARTED,
                RunEventRow.node_id.in_(list(steps)),
            )
            .order_by(RunEventRow.seq.desc())
            .limit(1)
        )


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
        kind=_KINDS.get(row.kind, "writer"),
        version=row.version,
        base_sha=row.base_sha,
        head_sha=row.head_sha,
        commits=row.commits,
        size=row.size,
        created_at=row.created_at,
        bundle_removed_at=row.bundle_removed_at,
    )
