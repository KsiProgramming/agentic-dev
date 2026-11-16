"""Rerun from a step (12.4): `POST /runs/{id}/rerun` with `from` makes a new run that starts at
one of the original's top-level steps, with that step's parameters edited at most, and says
why it cannot when it cannot."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import BranchBundle, RepoSource
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    Run,
    RunBranch,
    RunEventRow,
    create_run,
    list_audit_events,
    save_branch,
)

from .test_run_sandboxes import BASE, client

pytestmark = pytest.mark.integration

_ = client  # the fixture

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"


def three_steps() -> WorkflowSpec:
    path = SPECS / "three-step-sequence.json"
    return parse_spec(json.loads(path.read_text(encoding="utf-8")))


async def ended_run(
    sessions: async_sessionmaker[AsyncSession], started: list[str], **values: Any
) -> UUID:
    """A failed three-step run on a repo that started `started`, with its base commit."""
    repo = RepoSource(url="https://github.com/acme/hello")
    run_id = await create_run(sessions, three_steps(), "go", repo)
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(**{"status": "failed", "base_sha": BASE, **values})
        )
        for seq, node in enumerate(started, start=1):
            session.add(
                RunEventRow(
                    run_id=run_id, seq=seq, type="node_started", node_id=node, payload={},
                    created_at=now,
                )
            )  # fmt: skip
    return run_id


async def save(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    key: str,
    step: str | None,
    wip: bool = False,
) -> None:
    prefix = "wip" if wip else "agent"
    bundle = BranchBundle(
        branch=f"{prefix}/{run_id}/{key}", base_sha=BASE, data=b"b", head_sha="1" * 40, commits=1
    )
    await save_branch(sessions, run_id, key, "wip" if wip else "writer", bundle, step=step)


async def test_a_rerun_from_a_step_edits_only_that_step(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    original = await ended_run(sessions, ["step-1", "step-2", "step-3"])
    await save(sessions, original, "step-1", "step-1")
    body = {
        "from": {
            "node_id": "step-3",
            "set_params": [{"path": "instructions", "value": "Review it kindly."}],
        }
    }

    response = await client.post(f"/runs/{original}/rerun", json=body)

    assert response.status_code == 202, response.text
    new_id = response.json()["run_id"]
    async with sessions() as session:
        rerun = await session.get(Run, UUID(new_id))
        source = await session.get(Run, original)
    assert rerun is not None and source is not None
    assert rerun.rerun_of == original
    assert rerun.rerun_from == {"node_id": "step-3", "use_wip": False, "edited": ["instructions"]}
    assert rerun.base_sha == BASE
    steps = rerun.spec["root"]["steps"]  # type: ignore[index]
    assert steps[2]["instructions"] == "Review it kindly."  # type: ignore[index]
    assert steps[1]["instructions"] == source.spec["root"]["steps"][1]["instructions"]  # type: ignore[index]
    assert source.rerun_from is None and source.status == "failed"

    detail = (await client.get(f"/runs/{new_id}")).json()
    assert detail["rerun_from"] == {
        "run_id": str(original), "node_id": "step-3", "use_wip": False, "edited": ["instructions"],
    }  # fmt: skip
    (entry,), _ = await list_audit_events(
        sessions, DEFAULT_WORKSPACE_ID, actions=["run.rerun"], run_id=UUID(new_id)
    )
    assert entry.details["from"] == rerun.rerun_from
    assert "Review it kindly." not in json.dumps(entry.details)


async def test_use_wip_needs_uncommitted_work_from_that_step(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    original = await ended_run(sessions, ["step-1", "step-2"])
    body = {"from": {"node_id": "step-2", "use_wip": True}}

    refused = await client.post(f"/runs/{original}/rerun", json=body)
    assert refused.status_code == 409
    assert "no uncommitted work" in refused.json()["detail"]

    await save(sessions, original, "step-2", "step-2", wip=True)
    assert (await client.post(f"/runs/{original}/rerun", json=body)).status_code == 202


@pytest.mark.parametrize(
    ("from_", "status", "says"),
    [
        ({"node_id": "nope"}, 422, "not a top-level step"),
        ({"node_id": "step-3"}, 409, "never reached"),
        (
            {"node_id": "step-2", "set_params": [{"path": "id", "value": "x"}]},
            422,
            "",
        ),
    ],
)
async def test_a_step_that_cannot_be_rerun_from_is_refused(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    from_: dict[str, Any],
    status: int,
    says: str,
) -> None:
    original = await ended_run(sessions, ["step-1", "step-2"])

    response = await client.post(f"/runs/{original}/rerun", json={"from": from_})

    assert response.status_code == status, response.text
    assert says in response.json()["detail"]


async def test_code_saved_before_12_4_or_dropped_is_refused(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    old = await ended_run(sessions, ["step-1", "step-2"])
    await save(sessions, old, "step-1", None)
    response = await client.post(f"/runs/{old}/rerun", json={"from": {"node_id": "step-2"}})
    assert response.status_code == 409
    assert "saved before" in response.json()["detail"]

    swept = await ended_run(sessions, ["step-1", "step-2"])
    await save(sessions, swept, "step-1", "step-1")
    async with sessions.begin() as session:
        await session.execute(
            update(RunBranch)
            .where(RunBranch.run_id == swept)
            .values(data=None, bundle_removed_at=datetime.now(UTC))
        )
    response = await client.post(f"/runs/{swept}/rerun", json={"from": {"node_id": "step-2"}})
    assert response.status_code == 409
    assert "removed" in response.json()["detail"]


async def test_a_run_still_going_is_not_rerun_from_a_step(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    running = await ended_run(sessions, ["step-1"], status="running")
    response = await client.post(f"/runs/{running}/rerun", json={"from": {"node_id": "step-1"}})
    assert response.status_code == 409
