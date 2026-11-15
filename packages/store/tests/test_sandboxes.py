"""A failed, cancelled or expired run keeps its code (12.3): kept sandboxes, their sweep, the
changed files kept with each saved version, uncommitted work, and the bundles' retention."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import FileChange
from agentic_engine.policy import (
    BRANCH_RETENTION_DAYS,
    PLATFORM_POLICY,
    SANDBOX_TTL_S,
    PolicyOverrides,
    effective_policy,
)
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import BranchBundle
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    Run,
    RunNotFoundError,
    SandboxNotKeptError,
    create_run,
    drop_old_bundles,
    kept_sandbox_run_ids,
    latest_branches,
    list_audit_events,
    remove_expired_sandboxes,
    request_sandbox_removal,
    sandbox_info,
    save_branch,
    saved_changes,
)

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
BASE = "a" * 40


def single_agent() -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / "single-agent.json").read_text(encoding="utf-8")))


async def new_run(sessions: async_sessionmaker[AsyncSession], **values: Any) -> UUID:
    run_id = await create_run(sessions, single_agent(), "go")
    if values:
        await set_run(sessions, run_id, **values)
    return run_id


async def set_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID, **values: Any) -> None:
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(**values))


async def get(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> Run:
    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    return run


def ago(**delta: float) -> Any:
    return func.now() - timedelta(**delta)


# Policy


def test_the_retention_limits_default_below_their_ceiling() -> None:
    assert PLATFORM_POLICY.sandbox_ttl_s == SANDBOX_TTL_S == 24 * 3600
    assert PLATFORM_POLICY.branch_retention_days == BRANCH_RETENTION_DAYS == 30
    raised = effective_policy(PolicyOverrides(sandbox_ttl_s=48 * 3600, branch_retention_days=60))
    assert (raised.sandbox_ttl_s, raised.branch_retention_days) == (48 * 3600, 60)
    capped = effective_policy(PolicyOverrides(sandbox_ttl_s=10**7, branch_retention_days=10**4))
    assert (capped.sandbox_ttl_s, capped.branch_retention_days) == (72 * 3600, 90)
    # The other limits still only go down.
    assert effective_policy(PolicyOverrides(agents_alive=100)).agents_alive == 8


# Sandbox state


def test_a_run_s_sandbox_state_follows_its_columns() -> None:
    at = datetime(2026, 11, 15, tzinfo=UTC)
    assert sandbox_info("running", None, None).state == "running"
    assert sandbox_info("waiting", None, None).state == "running"
    assert sandbox_info("completed", None, None).state == "none"
    assert sandbox_info("failed", at, None).model_dump() == {
        "state": "kept",
        "kept_until": at,
        "removed_at": None,
    }
    assert sandbox_info("cancelled", at, at).state == "removed"


async def test_the_sweep_removes_only_sandboxes_past_their_time(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    expired = await new_run(sessions, status="failed", sandbox_kept_until=ago(minutes=1))
    kept = await new_run(
        sessions, status="failed", sandbox_kept_until=func.now() + timedelta(hours=1)
    )
    gone = await new_run(
        sessions, status="failed", sandbox_kept_until=ago(hours=2), sandbox_removed_at=ago(hours=1)
    )
    assert {expired, kept} <= await kept_sandbox_run_ids(sessions)
    assert gone not in await kept_sandbox_run_ids(sessions)

    removed: list[UUID] = []

    async def remove(run_id: UUID) -> None:
        removed.append(run_id)

    swept = await remove_expired_sandboxes(sessions, remove)

    assert expired in swept and expired in removed
    assert kept not in removed and gone not in removed
    assert (await get(sessions, expired)).sandbox_removed_at is not None
    assert expired not in await kept_sandbox_run_ids(sessions)
    entries, _ = await list_audit_events(sessions, DEFAULT_WORKSPACE_ID, run_id=expired)
    assert [(e.action, e.actor_type) for e in entries] == [
        ("sandbox.removed", "system"),
        ("run.created", "user"),
    ]
    assert await remove_expired_sandboxes(sessions, remove) == []


async def test_a_sandbox_that_cannot_be_removed_is_left_for_the_next_sweep(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    stuck = await new_run(sessions, status="failed", sandbox_kept_until=ago(minutes=1))

    async def fail(run_id: UUID) -> None:
        if run_id == stuck:
            raise RuntimeError("docker is down")

    assert stuck not in await remove_expired_sandboxes(sessions, fail)
    run = await get(sessions, stuck)
    assert run.sandbox_removed_at is None
    await set_run(sessions, stuck, sandbox_removed_at=func.now())  # out of other tests' sweeps


async def test_workers_share_the_sweep_without_removing_a_sandbox_twice(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    runs = {
        await new_run(sessions, status="failed", sandbox_kept_until=ago(minutes=1)) for _ in "abc"
    }
    removed: list[UUID] = []

    async def slow(run_id: UUID) -> None:
        await asyncio.sleep(0.05)
        removed.append(run_id)

    await asyncio.gather(*(remove_expired_sandboxes(sessions, slow) for _ in range(3)))

    mine = [r for r in removed if r in runs]
    assert sorted(mine) == sorted(runs)


async def test_a_user_asks_for_a_kept_sandbox_to_go_now(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    later = datetime.now(UTC) + timedelta(hours=5)
    run_id = await new_run(sessions, status="failed", sandbox_kept_until=later)

    info = await request_sandbox_removal(sessions, run_id)
    again = await request_sandbox_removal(sessions, run_id)

    assert info.state == "kept" and info.kept_until is not None and info.kept_until < later
    assert again.kept_until == info.kept_until
    entries, _ = await list_audit_events(sessions, DEFAULT_WORKSPACE_ID, run_id=run_id)
    assert [e.action for e in entries] == ["sandbox.remove_requested", "run.created"]
    assert entries[0].details == {"kept_until": later.isoformat()}
    assert run_id in await remove_expired_sandboxes(sessions, lambda _: asyncio.sleep(0))


async def test_only_a_kept_sandbox_can_be_removed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    running = await new_run(sessions, status="running")
    removed = await new_run(
        sessions, status="failed", sandbox_kept_until=ago(hours=1), sandbox_removed_at=ago(hours=1)
    )
    for run_id in (running, removed):
        with pytest.raises(SandboxNotKeptError):
            await request_sandbox_removal(sessions, run_id)
    with pytest.raises(RunNotFoundError):
        await request_sandbox_removal(sessions, UUID(int=7))


# Saved changes and uncommitted work


def change(path: str, after: str) -> FileChange:
    return FileChange(
        node_id="writer", path=path, status="added", editable=True, after=after, before=None
    )


def bundle(branch: str, head: str) -> BranchBundle:
    return BranchBundle(branch=branch, base_sha=BASE, data=b"bundle", head_sha=head, commits=1)


async def test_each_version_keeps_the_files_it_changed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await new_run(sessions)
    writer, wip = f"agent/{run_id}/writer", f"wip/{run_id}/writer"
    await save_branch(
        sessions, run_id, "writer", "writer", bundle(writer, "1" * 40), [change("a.md", "a\n")]
    )
    await save_branch(
        sessions,
        run_id,
        "writer",
        "wip",
        bundle(wip, "2" * 40),
        [change("a.md", "a\n"), change("b.md", "b\n")],
    )
    await save_branch(
        sessions,
        run_id,
        "other",
        "writer",
        bundle(f"agent/{run_id}/other", "3" * 40),
        None,
        "git failed",
    )

    shown = {c.branch: c for c in await saved_changes(sessions, run_id)}

    assert [f.path for f in shown[writer].changes or []] == ["a.md"]
    assert shown[wip].kind == "wip"
    assert [f.path for f in shown[wip].changes or []] == ["a.md", "b.md"]
    assert shown[f"agent/{run_id}/other"].changes_error == "git failed"
    # Uncommitted work is never put back into a sandbox.
    assert {b.branch for b in await latest_branches(sessions, run_id)} == {
        writer,
        f"agent/{run_id}/other",
    }


async def test_old_bundles_are_dropped_and_their_changes_stay(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    old = await new_run(sessions, status="failed", finished_at=ago(days=31))
    short = await new_run(sessions, status="failed", finished_at=ago(days=3))
    await set_run(
        sessions, short, policy={**(await get(sessions, short)).policy, "branch_retention_days": 2}
    )
    recent = await new_run(sessions, status="failed", finished_at=ago(days=1))
    running = await new_run(sessions, status="running")
    for run_id in (old, short, recent, running):
        branch = f"agent/{run_id}/writer"
        await save_branch(
            sessions, run_id, "writer", "writer", bundle(branch, "1" * 40), [change("a.md", "a\n")]
        )

    dropped = await drop_old_bundles(sessions)

    assert dropped >= 2
    for run_id, gone in ((old, True), (short, True), (recent, False), (running, False)):
        [saved] = await saved_changes(sessions, run_id)
        assert (saved.bundle_removed_at is not None) == gone
        assert [f.path for f in saved.changes or []] == ["a.md"]
        assert bool(await latest_branches(sessions, run_id)) != gone
    assert await drop_old_bundles(sessions) == 0
