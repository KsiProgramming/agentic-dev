"""Rerun from a step (12.4): the code a run had before one of its top-level steps, under the new
run's branch names; the step a run ended in; and the artifacts a rerun carries."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_sandbox import BranchBundle
from agentic_store import (
    PostgresArtifactStore,
    RerunBranchesError,
    RunArtifact,
    RunBranch,
    RunEventRow,
    copy_run_artifacts,
    has_uncommitted,
    last_started_step,
    rerun_branches,
    save_branch,
)

from .test_branches import BASE, new_run

pytestmark = pytest.mark.integration


def bundle(
    run: UUID, key: str, head: str, data: bytes = b"bundle", wip: bool = False
) -> BranchBundle:
    prefix = "wip" if wip else "agent"
    return BranchBundle(
        branch=f"{prefix}/{run}/{key}", base_sha=BASE, data=data, head_sha=head, commits=1
    )


async def test_the_code_before_a_step_is_each_branch_s_last_version_saved_before_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    source, target = await new_run(sessions), uuid4()
    await save_branch(
        sessions, source, "write", "writer", bundle(source, "write", "1" * 40, b"v1"), step="write"
    )
    await save_branch(
        sessions, source, "write", "writer", bundle(source, "write", "2" * 40, b"v2"), step="polish"
    )
    await save_branch(
        sessions, source, "fix", "integration", bundle(source, "fix", "3" * 40), step="fix"
    )
    await save_branch(
        sessions, source, "review", "writer", bundle(source, "review", "4" * 40), step="review"
    )

    got = await rerun_branches(sessions, source, target, ["write", "fix"])

    assert [(b.branch, b.source, b.head_sha, b.data) for b in got] == [
        (f"agent/{target}/fix", f"agent/{source}/fix", "3" * 40, b"bundle"),
        (f"agent/{target}/write", f"agent/{source}/write", "1" * 40, b"v1"),
    ]
    assert await rerun_branches(sessions, source, target, []) == []


async def test_uncommitted_work_replaces_its_writer_s_branch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    source, target = await new_run(sessions), uuid4()
    await save_branch(
        sessions, source, "write", "writer", bundle(source, "write", "1" * 40), step="write"
    )
    await save_branch(
        sessions, source, "write", "writer", bundle(source, "write", "2" * 40), step="review"
    )
    await save_branch(
        sessions,
        source,
        "write",
        "wip",
        bundle(source, "write", "5" * 40, b"wip", wip=True),
        step="review",
    )

    assert await has_uncommitted(sessions, source, "review")
    assert not await has_uncommitted(sessions, source, "write")
    (got,) = await rerun_branches(sessions, source, target, ["write"], wip_step="review")

    assert (got.branch, got.source, got.data) == (
        f"agent/{target}/write", f"wip/{source}/write", b"wip",
    )  # fmt: skip


async def test_versions_saved_before_12_4_cannot_be_rerun_from_a_step(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    source = await new_run(sessions)
    await save_branch(sessions, source, "write", "writer", bundle(source, "write", "1" * 40))

    with pytest.raises(RerunBranchesError, match="saved before"):
        await rerun_branches(sessions, source, uuid4(), ["write"])


async def test_a_dropped_bundle_cannot_be_restored(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    source = await new_run(sessions)
    await save_branch(
        sessions, source, "write", "writer", bundle(source, "write", "1" * 40), step="write"
    )
    async with sessions.begin() as session:
        await session.execute(
            update(RunBranch)
            .where(RunBranch.run_id == source)
            .values(data=None, bundle_removed_at=datetime.now(UTC))
        )

    with pytest.raises(RerunBranchesError, match="removed"):
        await rerun_branches(sessions, source, uuid4(), ["write"])
    # Checking without the bundles says the same.
    with pytest.raises(RerunBranchesError, match="removed"):
        await rerun_branches(sessions, source, uuid4(), ["write"], with_data=False)


async def test_the_step_a_run_ended_in_is_the_last_top_level_step_it_started(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await new_run(sessions)
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        for seq, node in enumerate(["outline", "fix", "worker", "review", "worker"], start=1):
            session.add(
                RunEventRow(
                    run_id=run_id, seq=seq, type="node_started", node_id=node, payload={},
                    created_at=now,
                )
            )  # fmt: skip

    assert await last_started_step(sessions, run_id, ["outline", "fix", "review"]) == "review"
    assert await last_started_step(sessions, run_id, ["outline"]) == "outline"
    assert await last_started_step(sessions, run_id, []) is None


async def test_a_rerun_copies_the_artifact_versions_it_carries(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    source, target = await new_run(sessions), await new_run(sessions)
    store = PostgresArtifactStore(sessions, source)
    for content in ["one", "two", "three"]:
        await store.put("findings.json", "audit", content)

    assert await copy_run_artifacts(sessions, source, target, {"findings.json": 2}) == 2
    assert await copy_run_artifacts(sessions, source, target, {"findings.json": 2}) == 0

    async with sessions() as session:
        copied = (
            await session.scalars(
                select(RunArtifact.version)
                .where(RunArtifact.run_id == target)
                .order_by(RunArtifact.version)
            )
        ).all()
    assert copied == [1, 2]
