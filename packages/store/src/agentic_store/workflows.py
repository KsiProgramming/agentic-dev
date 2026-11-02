"""Stored workflows (5.1): each change is a batch of graph operations that makes a new, immutable
version (`workflow_versions`). A change names the version it started from, so two editors never
overwrite each other."""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import GraphOp, apply_ops
from agentic_store.audit import audit
from agentic_store.connections import WorkspaceNotFoundError
from agentic_store.models import Workflow, WorkflowVersion, Workspace


class WorkflowExistsError(Exception):
    """The workspace already has a workflow with this id."""


class WorkflowNotFoundError(LookupError):
    """No workflow (or no version of it) has this id in the workspace."""


class VersionConflictError(Exception):
    """A change started from a version that is not the latest any more."""

    def __init__(self, latest_version: int) -> None:
        super().__init__(f"the latest version is {latest_version}")
        self.latest_version = latest_version


class StoredWorkflowVersion(BaseModel):
    """One version of a workflow, as the API shows it."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    version: int
    base_version: int | None
    created_at: datetime
    spec: dict[str, JsonValue]
    ops: list[JsonValue] | None


async def create_workflow(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, spec: Mapping[str, JsonValue]
) -> StoredWorkflowVersion:
    """Store `spec` (a decoded workflow spec) as version 1 of the workflow its `id` names.
    Raises `WorkspaceNotFoundError` and `WorkflowExistsError`."""
    workflow_id = cast(str, spec["id"])
    async with sessions.begin() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        if await session.get(Workflow, (workspace_id, workflow_id)) is not None:
            raise WorkflowExistsError(workflow_id)
        session.add(Workflow(workspace_id=workspace_id, id=workflow_id, latest_version=1))
        await session.flush()
        row = WorkflowVersion(
            workspace_id=workspace_id, workflow_id=workflow_id, version=1, spec=dict(spec)
        )
        session.add(row)
        audit(
            session,
            workspace_id,
            "workflow.created",
            details={"workflow_id": workflow_id, "version": 1},
        )
        await session.flush()
        await session.refresh(row)
        return _stored(row)


async def update_workflow(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    workflow_id: str,
    base_version: int,
    ops: Sequence[GraphOp],
) -> StoredWorkflowVersion:
    """Apply `ops` to version `base_version` and store the result as the next version, with the
    ops. Raises `WorkflowNotFoundError`, `VersionConflictError` when `base_version` is not the
    latest, and the engine's `OpError` when the ops cannot apply (nothing is stored then)."""
    async with sessions.begin() as session:
        workflow = await session.get(Workflow, (workspace_id, workflow_id), with_for_update=True)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if base_version != workflow.latest_version:
            raise VersionConflictError(workflow.latest_version)
        base = await session.get(WorkflowVersion, (workspace_id, workflow_id, base_version))
        assert base is not None, "a workflow's latest version is stored with it"
        spec = cast(dict[str, JsonValue], apply_ops(base.spec, ops))
        version = base_version + 1
        dumped: list[JsonValue] = [
            op.model_dump(mode="json", by_alias=True, exclude_unset=True) for op in ops
        ]
        row = WorkflowVersion(
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            version=version,
            spec=spec,
            base_version=base_version,
            ops=dumped,
        )
        session.add(row)
        workflow.latest_version = version
        workflow.updated_at = datetime.now(UTC)
        kinds = Counter(op.op for op in ops)
        details: dict[str, JsonValue] = {
            "workflow_id": workflow_id,
            "version": version,
            "base_version": base_version,
            "op_count": len(ops),
            "ops": dict(sorted(kinds.items())),
        }
        audit(session, workspace_id, "workflow.updated", details=details)
        await session.flush()
        await session.refresh(row)
        return _stored(row)


async def get_workflow_version(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    workflow_id: str,
    version: int | None = None,
) -> StoredWorkflowVersion:
    """Version `version` of the workflow, the latest by default. Raises `WorkflowNotFoundError`
    for an unknown workflow or version."""
    async with sessions() as session:
        if version is None:
            workflow = await session.get(Workflow, (workspace_id, workflow_id))
            if workflow is None:
                raise WorkflowNotFoundError(workflow_id)
            version = workflow.latest_version
        row = await session.get(WorkflowVersion, (workspace_id, workflow_id, version))
    if row is None:
        raise WorkflowNotFoundError(workflow_id)
    return _stored(row)


async def list_workflow_versions(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, workflow_id: str
) -> list[StoredWorkflowVersion]:
    """Every version of the workflow, newest first. Raises `WorkflowNotFoundError`."""
    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(WorkflowVersion)
                .where(
                    WorkflowVersion.workspace_id == workspace_id,
                    WorkflowVersion.workflow_id == workflow_id,
                )
                .order_by(WorkflowVersion.version.desc())
            )
        )
    if not rows:
        raise WorkflowNotFoundError(workflow_id)
    return [_stored(row) for row in rows]


def _stored(row: WorkflowVersion) -> StoredWorkflowVersion:
    return StoredWorkflowVersion(
        workflow_id=row.workflow_id,
        version=row.version,
        base_version=row.base_version,
        created_at=row.created_at,
        spec=row.spec,
        ops=row.ops,
    )
