"""Writers' commits saved outside the sandbox (12.2): the run's base commit, and every saved
version of its branches."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import MAX_TAKE_FILE_BYTES, BranchBundle
from agentic_store import (
    BundleTooLargeError,
    RunBranch,
    create_run,
    get_run,
    latest_branches,
    list_saved_branches,
    record_base_sha,
    save_branch,
)

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
BASE = "a" * 40


def single_agent() -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / "single-agent.json").read_text(encoding="utf-8")))


def bundle(branch: str, head: str, data: bytes = b"bundle", commits: int = 1) -> BranchBundle:
    return BranchBundle(branch=branch, base_sha=BASE, data=data, head_sha=head, commits=commits)


async def new_run(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    return await create_run(sessions, single_agent(), "go")


async def versions(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> int:
    async with sessions() as session:
        count = await session.scalar(
            select(func.count()).select_from(RunBranch).where(RunBranch.run_id == run_id)
        )
    return int(count or 0)


async def test_a_run_s_base_commit_is_recorded_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await new_run(sessions)
    fresh = await get_run(sessions, run_id)
    assert fresh is not None and fresh.base_sha is None

    assert await record_base_sha(sessions, run_id, BASE) == BASE
    assert await record_base_sha(sessions, run_id, "b" * 40) == BASE

    run = await get_run(sessions, run_id)
    assert run is not None
    assert run.base_sha == BASE


async def test_only_a_commit_id_is_a_base(sessions: async_sessionmaker[AsyncSession]) -> None:
    run_id = await new_run(sessions)
    with pytest.raises(ValueError, match="not a commit id"):
        await record_base_sha(sessions, run_id, "HEAD")


async def test_versions_are_appended_only_when_the_tip_moved(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await new_run(sessions)
    branch = f"agent/{run_id}/writer"

    first = await save_branch(sessions, run_id, "writer", "writer", bundle(branch, "1" * 40))
    same = await save_branch(sessions, run_id, "writer", "writer", bundle(branch, "1" * 40))
    moved = await save_branch(
        sessions, run_id, "writer", "writer", bundle(branch, "2" * 40, b"newer", 2)
    )

    assert first is not None and first.version == 1
    assert same is None
    assert moved is not None
    assert (moved.version, moved.head_sha, moved.commits, moved.size) == (2, "2" * 40, 2, 5)
    assert await versions(sessions, run_id) == 2


async def test_the_latest_version_of_each_branch_is_restored(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await new_run(sessions)
    writer, merged = f"agent/{run_id}/writer", f"agent/{run_id}/lead"
    await save_branch(sessions, run_id, "writer", "writer", bundle(writer, "1" * 40, b"old"))
    await save_branch(sessions, run_id, "writer", "writer", bundle(writer, "2" * 40, b"new"))
    await save_branch(sessions, run_id, "lead", "integration", bundle(merged, "3" * 40, b"m"))
    other = await new_run(sessions)
    await save_branch(sessions, other, "writer", "writer", bundle(f"agent/{other}/w", "4" * 40))

    restored = await latest_branches(sessions, run_id)
    listed = await list_saved_branches(sessions, run_id)

    assert [(b.branch, b.head_sha, b.data) for b in restored] == [
        (merged, "3" * 40, b"m"),
        (writer, "2" * 40, b"new"),
    ]
    assert [(s.node_key, s.kind, s.version) for s in listed] == [
        ("lead", "integration", 1),
        ("writer", "writer", 2),
    ]


async def test_a_bundle_over_the_cap_is_not_saved(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await new_run(sessions)
    huge = bundle(f"agent/{run_id}/writer", "1" * 40, b"x" * (MAX_TAKE_FILE_BYTES + 1))

    with pytest.raises(BundleTooLargeError, match="over the 64 MB"):
        await save_branch(sessions, run_id, "writer", "writer", huge)
    assert await versions(sessions, run_id) == 0
