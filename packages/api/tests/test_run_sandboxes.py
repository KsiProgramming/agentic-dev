"""A failed, cancelled or expired run keeps its code (12.3): its sandbox's state on `GET
/runs/{id}`, what its writers changed (`GET /runs/{id}/changes`), and removing a kept sandbox
now (`DELETE /runs/{id}/sandbox`)."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.gate import FileChange
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import BranchBundle, RepoSource
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    BranchKind,
    Run,
    create_run,
    list_audit_events,
    save_branch,
)

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
BASE = "a" * 40


def single_agent() -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / "single-agent.json").read_text(encoding="utf-8")))


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def new_run(sessions: async_sessionmaker[AsyncSession], **values: Any) -> UUID:
    repo = RepoSource(url="https://github.com/acme/hello")
    run_id = await create_run(sessions, single_agent(), "go", repo)
    if values:
        async with sessions.begin() as session:
            await session.execute(update(Run).where(Run.id == run_id).values(**values))
    return run_id


def change(node_id: str, path: str) -> FileChange:
    return FileChange(
        node_id=node_id, path=path, status="added", editable=True, before=None, after="x\n"
    )


async def test_a_run_says_what_became_of_its_sandbox(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    until = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
    running = await new_run(sessions, status="running")
    kept = await new_run(sessions, status="failed", sandbox_kept_until=until)
    removed = await new_run(
        sessions,
        status="cancelled",
        sandbox_kept_until=until,
        sandbox_removed_at=until + timedelta(seconds=30),
    )
    completed = await new_run(sessions, status="completed")

    async def sandbox(run_id: UUID) -> dict[str, Any]:
        response = await client.get(f"/runs/{run_id}")
        assert response.status_code == 200, response.text
        return response.json()["sandbox"]

    assert await sandbox(running) == {"state": "running", "kept_until": None, "removed_at": None}
    assert await sandbox(kept) == {
        "state": "kept",
        "kept_until": "2026-11-16T09:00:00Z",
        "removed_at": None,
    }
    assert (await sandbox(removed))["state"] == "removed"
    assert (await sandbox(removed))["removed_at"] == "2026-11-16T09:00:30Z"
    assert (await sandbox(completed))["state"] == "none"
    # The runs list is unchanged.
    listed = (await client.get("/runs", params={"limit": 1})).json()["items"]
    assert "sandbox" not in listed[0]


async def test_what_the_writers_changed_is_read_from_what_was_saved(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    run_id = await new_run(sessions, status="failed")
    branches: list[tuple[str, BranchKind, str, list[FileChange]]] = [
        ("writer", "writer", f"agent/{run_id}/writer", [change("writer", "NOTES.md")]),
        ("fix.b1", "writer", f"agent/{run_id}/fix.b1", [change("fix.b1", "a.py")]),
        ("fix", "integration", f"agent/{run_id}/fix", [change("fix", "a.py")]),
        ("writer", "wip", f"wip/{run_id}/writer", [change("writer", "DRAFT.md")]),
    ]
    for key, kind, branch, files in branches:
        bundle = BranchBundle(branch=branch, base_sha=BASE, data=b"b", head_sha="1" * 40, commits=1)
        await save_branch(sessions, run_id, key, kind, bundle, files)

    response = await client.get(f"/runs/{run_id}/changes")

    assert response.status_code == 200, response.text
    got = {b["branch"]: b for b in response.json()}
    assert [(b["node_id"], b["key"], b["kind"]) for b in response.json()] == [
        ("fix", "fix", "integration"),
        ("fix", "fix.b1", "writer"),
        ("writer", "writer", "writer"),
        ("writer", "writer", "wip"),
    ]
    writer = got[f"agent/{run_id}/writer"]
    assert writer["changes"][0]["path"] == "NOTES.md"
    assert (writer["version"], writer["head"], writer["commits"]) == (1, "1" * 40, 1)
    assert writer["bundle_removed_at"] is None and writer["changes_error"] is None
    assert (await client.get(f"/runs/{uuid4()}/changes")).status_code == 404


async def test_a_kept_sandbox_can_be_removed_now(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    later = datetime.now(UTC) + timedelta(hours=12)
    run_id = await new_run(sessions, status="failed", sandbox_kept_until=later)

    response = await client.delete(f"/runs/{run_id}/sandbox")
    again = await client.delete(f"/runs/{run_id}/sandbox")

    assert response.status_code == 202, response.text
    assert response.json()["state"] == "kept"
    assert datetime.fromisoformat(response.json()["kept_until"]) < later
    assert again.status_code == 202
    entries, _ = await list_audit_events(sessions, DEFAULT_WORKSPACE_ID, run_id=run_id)
    assert [e.action for e in entries].count("sandbox.remove_requested") == 1
    async with sessions.begin() as session:  # out of other tests' sweeps
        await session.execute(
            update(Run).where(Run.id == run_id).values(sandbox_removed_at=func.now())
        )


async def test_only_a_kept_sandbox_can_be_removed(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    running = await new_run(sessions, status="running")
    completed = await new_run(sessions, status="completed")

    for run_id in (running, completed):
        assert (await client.delete(f"/runs/{run_id}/sandbox")).status_code == 409
    assert (await client.delete(f"/runs/{uuid4()}/sandbox")).status_code == 404
