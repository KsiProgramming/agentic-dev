"""Stored workflows (5.1): each change is a batch of graph operations that makes a new, immutable
version (`workflow_versions`). A change names the version it started from, so two editors never
overwrite each other. A restore (5.7) stores a copy of an older version as the next one.

Composites (6.6): a version may be published (`workflow_publications`, append only); a workflow
with a published version is a composite, which other workflows call by a published version. An
`extract` op stores the workflow it makes as version 1 with the caller's new version, both or
neither."""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import GraphOp, apply_graph_ops, subflow_refs
from agentic_store.audit import audit
from agentic_store.connections import WorkspaceNotFoundError
from agentic_store.models import Workflow, WorkflowPublication, WorkflowVersion, Workspace


class WorkflowExistsError(Exception):
    """The workspace already has a workflow with this id."""


class WorkflowNotFoundError(LookupError):
    """No workflow (or no version of it) has this id in the workspace."""


class VersionConflictError(Exception):
    """A change started from a version that is not the latest any more."""

    def __init__(self, latest_version: int) -> None:
        super().__init__(f"the latest version is {latest_version}")
        self.latest_version = latest_version


class AlreadyLatestError(Exception):
    """A restore named the latest version, which needs no restoring."""


class AlreadyPublishedError(Exception):
    """The version is published already."""


class StoredWorkflowVersion(BaseModel):
    """One version of a workflow, as the API shows it."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    version: int
    base_version: int | None
    created_at: datetime
    spec: dict[str, JsonValue]
    ops: list[JsonValue] | None
    restored_from: int | None = None
    published_at: datetime | None = None
    published_version: int | None = None
    extracted: str | None = None
    """With an `extract`: the id of the workflow it stored as version 1."""


class StoredWorkflowSummary(BaseModel):
    """A workflow in a workspace's list (5.8): its latest version's name and description."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    name: str
    description: str | None
    latest_version: int
    created_at: datetime
    updated_at: datetime
    published_version: int | None = None


class WorkflowCaller(BaseModel):
    """A workflow whose latest version calls another (6.6), and the version it calls."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    name: str
    latest_version: int
    calls_version: int


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
    ops. An `extract` among them also stores the workflow it makes as its version 1, in the same
    transaction. Raises `WorkflowNotFoundError`, `VersionConflictError` when `base_version` is not
    the latest, `WorkflowExistsError` when the extracted workflow's id is taken, and the engine's
    `OpError` when the ops cannot apply (nothing is stored then)."""
    async with sessions.begin() as session:
        workflow = await session.get(Workflow, (workspace_id, workflow_id), with_for_update=True)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if base_version != workflow.latest_version:
            raise VersionConflictError(workflow.latest_version)
        base = await session.get(WorkflowVersion, (workspace_id, workflow_id, base_version))
        assert base is not None, "a workflow's latest version is stored with it"
        applied = apply_graph_ops(base.spec, ops)
        spec = cast(dict[str, JsonValue], applied.spec)
        version = base_version + 1
        extracted: str | None = None
        if applied.extracted is not None:
            extracted = cast(str, applied.extracted["id"])
            if await session.get(Workflow, (workspace_id, extracted)) is not None:
                raise WorkflowExistsError(extracted)
            session.add(Workflow(workspace_id=workspace_id, id=extracted, latest_version=1))
            await session.flush()
            session.add(
                WorkflowVersion(
                    workspace_id=workspace_id,
                    workflow_id=extracted,
                    version=1,
                    spec=cast(dict[str, JsonValue], applied.extracted),
                )
            )
            audit(
                session,
                workspace_id,
                "workflow.created",
                details={
                    "workflow_id": extracted,
                    "version": 1,
                    "extracted_from": {"workflow_id": workflow_id, "version": version},
                },
            )
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
        published = await _publications(session, workspace_id, workflow_id)
        return _stored(row, published).model_copy(update={"extracted": extracted})


async def restore_workflow(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    workflow_id: str,
    base_version: int,
    version: int,
) -> StoredWorkflowVersion:
    """Store version `version`'s spec as the next version, with `restored_from` set to it and no
    ops. Raises `WorkflowNotFoundError` for an unknown workflow or version,
    `VersionConflictError` when `base_version` is not the latest, and `AlreadyLatestError` when
    `version` is the latest."""
    async with sessions.begin() as session:
        workflow = await session.get(Workflow, (workspace_id, workflow_id), with_for_update=True)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if base_version != workflow.latest_version:
            raise VersionConflictError(workflow.latest_version)
        if version == workflow.latest_version:
            raise AlreadyLatestError(version)
        source = await session.get(WorkflowVersion, (workspace_id, workflow_id, version))
        if source is None:
            raise WorkflowNotFoundError(workflow_id)
        latest = base_version + 1
        row = WorkflowVersion(
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            version=latest,
            spec=source.spec,
            base_version=base_version,
            restored_from=version,
        )
        session.add(row)
        workflow.latest_version = latest
        workflow.updated_at = datetime.now(UTC)
        audit(
            session,
            workspace_id,
            "workflow.restored",
            details={
                "workflow_id": workflow_id,
                "version": latest,
                "base_version": base_version,
                "restored_from": version,
            },
        )
        await session.flush()
        await session.refresh(row)
        return _stored(row, await _publications(session, workspace_id, workflow_id))


async def publish_workflow(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    workflow_id: str,
    version: int,
) -> StoredWorkflowVersion:
    """Publish version `version` (6.6): the workflow becomes a composite, which other workflows
    call by this version. Whether the version can run is the caller's to check first. Raises
    `WorkflowNotFoundError` for an unknown workflow or version and `AlreadyPublishedError`."""
    async with sessions.begin() as session:
        workflow = await session.get(Workflow, (workspace_id, workflow_id), with_for_update=True)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        row = await session.get(WorkflowVersion, (workspace_id, workflow_id, version))
        if row is None:
            raise WorkflowNotFoundError(workflow_id)
        key = (workspace_id, workflow_id, version)
        if await session.get(WorkflowPublication, key) is not None:
            raise AlreadyPublishedError(version)
        session.add(
            WorkflowPublication(workspace_id=workspace_id, workflow_id=workflow_id, version=version)
        )
        audit(
            session,
            workspace_id,
            "workflow.published",
            details={"workflow_id": workflow_id, "version": version},
        )
        await session.flush()
        return _stored(row, await _publications(session, workspace_id, workflow_id))


async def list_callers(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, workflow_id: str
) -> list[WorkflowCaller]:
    """The workspace's workflows whose latest version calls `workflow_id` (6.6), by name, each
    with the version it calls (the newest, when it calls several). Raises
    `WorkflowNotFoundError` for an unknown workflow."""
    async with sessions() as session:
        if await session.get(Workflow, (workspace_id, workflow_id)) is None:
            raise WorkflowNotFoundError(workflow_id)
        rows = (await session.execute(_latest_versions(workspace_id))).all()
    callers: list[WorkflowCaller] = []
    for workflow, latest in rows:
        versions = [v for w, v in subflow_refs(latest.spec) if w == workflow_id]
        if workflow.id == workflow_id or not versions:
            continue
        callers.append(
            WorkflowCaller(
                workflow_id=workflow.id,
                name=cast(str, latest.spec.get("name", workflow.id)),
                latest_version=workflow.latest_version,
                calls_version=max(versions),
            )
        )
    return sorted(callers, key=lambda c: (c.name.casefold(), c.workflow_id))


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
        published = await _publications(session, workspace_id, workflow_id)
    if row is None:
        raise WorkflowNotFoundError(workflow_id)
    return _stored(row, published)


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
        published = await _publications(session, workspace_id, workflow_id)
    if not rows:
        raise WorkflowNotFoundError(workflow_id)
    return [_stored(row, published) for row in rows]


async def list_workflows(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> list[StoredWorkflowSummary]:
    """The workspace's workflows, the most recently changed first (by when their latest version
    was made), with their latest version's name and description."""
    async with sessions() as session:
        rows = (
            await session.execute(
                _latest_versions(workspace_id).order_by(
                    WorkflowVersion.created_at.desc(), Workflow.id
                )
            )
        ).all()
        published = await latest_publications(session, workspace_id)
    return [
        StoredWorkflowSummary(
            workflow_id=workflow.id,
            name=cast(str, latest.spec.get("name", workflow.id)),
            description=cast(str | None, latest.spec.get("description")),
            latest_version=workflow.latest_version,
            created_at=workflow.created_at,
            updated_at=latest.created_at,
            published_version=published.get(workflow.id),
        )
        for workflow, latest in rows
    ]


def _latest_versions(workspace_id: UUID) -> Select[Workflow, WorkflowVersion]:
    """Each workflow of the workspace with its latest version."""
    return (
        select(Workflow, WorkflowVersion)
        .join(
            WorkflowVersion,
            (WorkflowVersion.workspace_id == Workflow.workspace_id)
            & (WorkflowVersion.workflow_id == Workflow.id)
            & (WorkflowVersion.version == Workflow.latest_version),
        )
        .where(Workflow.workspace_id == workspace_id)
    )


class StoredComposite(BaseModel):
    """A composite of the workspace (6.6): its latest published version, with that version's
    name and description, as the palette lists it."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    version: int
    name: str
    description: str | None


async def list_composites(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> list[StoredComposite]:
    """The workspace's composites, by name: each at its latest published version."""
    async with sessions() as session:
        published = await latest_publications(session, workspace_id)
        if not published:
            return []
        rows = await session.scalars(
            select(WorkflowVersion).where(
                WorkflowVersion.workspace_id == workspace_id,
                tuple_(WorkflowVersion.workflow_id, WorkflowVersion.version).in_(
                    sorted(published.items())
                ),
            )
        )
        versions = list(rows)
    composites = [
        StoredComposite(
            workflow_id=row.workflow_id,
            version=row.version,
            name=cast(str, row.spec.get("name", row.workflow_id)),
            description=cast(str | None, row.spec.get("description")),
        )
        for row in versions
    ]
    return sorted(composites, key=lambda c: (c.name.casefold(), c.workflow_id))


async def latest_publications(session: AsyncSession, workspace_id: UUID) -> dict[str, int]:
    """Each composite of the workspace (6.6), by id, with its latest published version."""
    rows = await session.execute(
        select(WorkflowPublication.workflow_id, func.max(WorkflowPublication.version))
        .where(WorkflowPublication.workspace_id == workspace_id)
        .group_by(WorkflowPublication.workflow_id)
    )
    return {workflow_id: version for workflow_id, version in rows.all()}


async def _publications(
    session: AsyncSession, workspace_id: UUID, workflow_id: str
) -> dict[int, datetime]:
    """When each published version of the workflow was published."""
    rows = await session.execute(
        select(WorkflowPublication.version, WorkflowPublication.published_at).where(
            WorkflowPublication.workspace_id == workspace_id,
            WorkflowPublication.workflow_id == workflow_id,
        )
    )
    return {version: published_at for version, published_at in rows.all()}


def _stored(
    row: WorkflowVersion, published: Mapping[int, datetime] | None = None
) -> StoredWorkflowVersion:
    published = published or {}
    return StoredWorkflowVersion(
        workflow_id=row.workflow_id,
        version=row.version,
        base_version=row.base_version,
        created_at=row.created_at,
        spec=row.spec,
        ops=row.ops,
        restored_from=row.restored_from,
        published_at=published.get(row.version),
        published_version=max(published, default=None),
    )
