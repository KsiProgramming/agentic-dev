"""Stored workflows (5.1): each batch of graph operations makes a new, immutable version; a
restore (5.7) copies an older one as the next."""

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import GraphOp, OpError
from agentic_store import (
    AlreadyLatestError,
    AuditEvent,
    VersionConflictError,
    WorkflowExistsError,
    WorkflowNotFoundError,
    WorkspaceNotFoundError,
    create_workflow,
    create_workspace,
    get_workflow_version,
    list_workflow_versions,
    restore_workflow,
    update_workflow,
)

pytestmark = pytest.mark.integration

OPS: TypeAdapter[list[GraphOp]] = TypeAdapter(list[GraphOp])


def agent(node_id: str) -> dict[str, JsonValue]:
    return {"type": "agent", "id": node_id, "role": node_id, "instructions": f"Do {node_id}."}


def spec(workflow_id: str) -> dict[str, JsonValue]:
    return {
        "spec_version": "0",
        "id": workflow_id,
        "name": "Docs",
        "root": {"type": "sequence", "id": "main", "steps": [agent("plan"), agent("write")]},
    }


def ops(*items: dict[str, Any]) -> list[GraphOp]:
    return OPS.validate_python(list(items))


ADD_REVIEW = ops({"op": "addNode", "node": agent("review"), "at": {"after": "write"}})


async def new_workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    return (await create_workspace(sessions, f"workflows-{uuid4().hex[:8]}")).id


async def test_applying_ops_makes_a_new_version_and_keeps_the_old_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    first = await create_workflow(sessions, workspace_id, spec("docs"))
    assert (first.version, first.base_version, first.ops) == (1, None, None)

    second = await update_workflow(sessions, workspace_id, "docs", 1, ADD_REVIEW)

    assert (second.version, second.base_version) == (2, 1)
    assert second.ops == [{"op": "addNode", "node": agent("review"), "at": {"after": "write"}}]
    root = cast(dict[str, Any], second.spec["root"])
    assert [step["id"] for step in root["steps"]] == ["plan", "write", "review"]
    old = await get_workflow_version(sessions, workspace_id, "docs", 1)
    assert old.spec == spec("docs")
    assert (await get_workflow_version(sessions, workspace_id, "docs")).version == 2
    versions = await list_workflow_versions(sessions, workspace_id, "docs")
    assert [v.version for v in versions] == [2, 1]


async def test_a_stale_base_version_is_a_conflict(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await create_workflow(sessions, workspace_id, spec("docs"))
    await update_workflow(sessions, workspace_id, "docs", 1, ADD_REVIEW)

    with pytest.raises(VersionConflictError) as exc:
        await update_workflow(
            sessions, workspace_id, "docs", 1, ops({"op": "removeNode", "node_id": "plan"})
        )
    assert exc.value.latest_version == 2


async def test_ops_that_cannot_apply_store_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await create_workflow(sessions, workspace_id, spec("docs"))

    with pytest.raises(OpError) as exc:
        await update_workflow(
            sessions, workspace_id, "docs", 1, ops({"op": "removeNode", "node_id": "nope"})
        )
    assert exc.value.code == "unknown_node"
    assert [v.version for v in await list_workflow_versions(sessions, workspace_id, "docs")] == [1]


async def test_ids_are_per_workspace(sessions: async_sessionmaker[AsyncSession]) -> None:
    one, other = await new_workspace(sessions), await new_workspace(sessions)
    await create_workflow(sessions, one, spec("docs"))

    with pytest.raises(WorkflowExistsError):
        await create_workflow(sessions, one, spec("docs"))
    with pytest.raises(WorkflowNotFoundError):
        await get_workflow_version(sessions, other, "docs")
    with pytest.raises(WorkflowNotFoundError):
        await update_workflow(sessions, other, "docs", 1, ADD_REVIEW)
    with pytest.raises(WorkflowNotFoundError):
        await list_workflow_versions(sessions, other, "docs")
    await create_workflow(sessions, other, spec("docs"))  # the same id in another workspace
    with pytest.raises(WorkflowNotFoundError):
        await get_workflow_version(sessions, one, "docs", 9)
    with pytest.raises(WorkspaceNotFoundError):
        await create_workflow(sessions, uuid4(), spec("docs"))


async def test_versions_cannot_change(sessions: async_sessionmaker[AsyncSession]) -> None:
    workspace_id = await new_workspace(sessions)
    await create_workflow(sessions, workspace_id, spec("docs"))

    for statement in (
        "UPDATE workflow_versions SET spec = '{}' WHERE workspace_id = :w",
        "DELETE FROM workflow_versions WHERE workspace_id = :w",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with sessions.begin() as session:
                await session.execute(text(statement), {"w": workspace_id})


async def test_changes_are_audited_without_the_spec(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await create_workflow(sessions, workspace_id, spec("docs"))
    await update_workflow(
        sessions,
        workspace_id,
        "docs",
        1,
        ops(
            {"op": "addNode", "node": agent("review"), "at": {"after": "write"}},
            {"op": "setParam", "node_id": "plan", "path": "instructions", "value": "Plan."},
            {"op": "setParam", "node_id": "write", "path": "instructions", "value": "Write."},
        ),
    )

    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == workspace_id)
                .order_by(AuditEvent.id)
            )
        )
    assert [(r.action, r.details) for r in rows] == [
        ("workflow.created", {"workflow_id": "docs", "version": 1}),
        (
            "workflow.updated",
            {
                "workflow_id": "docs",
                "version": 2,
                "base_version": 1,
                "op_count": 3,
                "ops": {"addNode": 1, "setParam": 2},
            },
        ),
    ]


async def test_a_restore_copies_an_older_version_as_the_next(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await create_workflow(sessions, workspace_id, spec("docs"))
    second = await update_workflow(sessions, workspace_id, "docs", 1, ADD_REVIEW)
    await update_workflow(
        sessions, workspace_id, "docs", 2, ops({"op": "removeNode", "node_id": "plan"})
    )

    restored = await restore_workflow(sessions, workspace_id, "docs", 3, 1)

    assert (restored.version, restored.base_version, restored.ops) == (4, 3, None)
    assert (restored.restored_from, restored.spec) == (1, spec("docs"))
    assert await get_workflow_version(sessions, workspace_id, "docs", 2) == second
    assert (await get_workflow_version(sessions, workspace_id, "docs")).version == 4
    async with sessions() as session:
        row = await session.scalar(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.id.desc())
        )
    assert row is not None
    assert (row.action, row.details) == (
        "workflow.restored",
        {"workflow_id": "docs", "version": 4, "base_version": 3, "restored_from": 1},
    )


async def test_a_restore_is_refused_when_stale_latest_or_unknown(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await new_workspace(sessions)
    await create_workflow(sessions, workspace_id, spec("docs"))
    await update_workflow(sessions, workspace_id, "docs", 1, ADD_REVIEW)

    with pytest.raises(VersionConflictError):
        await restore_workflow(sessions, workspace_id, "docs", 1, 1)
    with pytest.raises(AlreadyLatestError):
        await restore_workflow(sessions, workspace_id, "docs", 2, 2)
    with pytest.raises(WorkflowNotFoundError):
        await restore_workflow(sessions, workspace_id, "docs", 2, 7)
    with pytest.raises(WorkflowNotFoundError):
        await restore_workflow(sessions, workspace_id, "nope", 1, 1)
    assert len(await list_workflow_versions(sessions, workspace_id, "docs")) == 2
