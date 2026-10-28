"""Run artifacts in Postgres (4.3): the `ArtifactStore` a worker gives the engine for one run, and
what the API reads back. Every version is kept (`run_artifacts`)."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.artifacts import Artifact, ArtifactRef, make_artifact, ref_of
from agentic_store.models import RunArtifact


class StoredArtifact(BaseModel):
    """One version of a run artifact as the API shows it, with how many versions it has and
    when this one was written."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int
    versions: int
    node_id: str
    media_type: str
    size: int
    sha256: str
    created_at: datetime


class PostgresArtifactStore:
    """The `ArtifactStore` of the run `run_id`, in `run_artifacts`."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
        self._sessions = sessions
        self._run_id = run_id

    async def put(
        self,
        name: str,
        node_id: str,
        content: str,
        output_schema: Mapping[str, JsonValue] | None = None,
    ) -> ArtifactRef:
        async with self._sessions.begin() as session:
            last = await session.scalar(
                select(func.max(RunArtifact.version)).where(
                    RunArtifact.run_id == self._run_id, RunArtifact.name == name
                )
            )
            artifact = make_artifact(name, (last or 0) + 1, node_id, content, output_schema)
            session.add(
                RunArtifact(
                    run_id=self._run_id,
                    **artifact.model_dump(exclude={"output_schema"}),
                    output_schema=artifact.output_schema,
                )
            )
        return ref_of(artifact)

    async def get(self, name: str, version: int | None = None) -> Artifact | None:
        async with self._sessions() as session:
            row = await session.scalar(_version(self._run_id, name, version))
        return _artifact(row) if row is not None else None

    async def latest(self) -> list[ArtifactRef]:
        return [
            ArtifactRef.model_validate(a.model_dump(include=set(ArtifactRef.model_fields)))
            for a in await list_run_artifacts(self._sessions, self._run_id)
        ]

    async def total_bytes(self) -> int:
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.sum(RunArtifact.size)).where(RunArtifact.run_id == self._run_id)
            )
        return int(total or 0)


async def list_run_artifacts(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[StoredArtifact]:
    """The latest version of each of the run's artifacts, by name."""
    versions = func.count().over(partition_by=RunArtifact.name).label("versions")
    newest = (
        func.row_number()
        .over(partition_by=RunArtifact.name, order_by=RunArtifact.version.desc())
        .label("newest")
    )
    ranked = select(RunArtifact, versions, newest).where(RunArtifact.run_id == run_id).subquery()
    async with sessions() as session:
        rows = await session.execute(
            select(ranked).where(ranked.c.newest == 1).order_by(ranked.c.name)
        )
        return [
            StoredArtifact(
                name=row.name,
                version=row.version,
                versions=row.versions,
                node_id=row.node_id,
                media_type=row.media_type,
                size=row.size,
                sha256=row.sha256,
                created_at=row.created_at,
            )
            for row in rows
        ]


async def get_run_artifact(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    name: str,
    version: int | None = None,
) -> tuple[Artifact, StoredArtifact] | None:
    """That version of the run's artifact `name` (its latest without one) with its content, and
    how it is listed; `None` if there is no such version."""
    async with sessions() as session:
        row = await session.scalar(_version(run_id, name, version))
        if row is None:
            return None
        count = await session.scalar(
            select(func.count()).where(RunArtifact.run_id == run_id, RunArtifact.name == name)
        )
    listed = StoredArtifact(
        name=row.name,
        version=row.version,
        versions=count or 0,
        node_id=row.node_id,
        media_type=row.media_type,
        size=row.size,
        sha256=row.sha256,
        created_at=row.created_at,
    )
    return _artifact(row), listed


def _version(run_id: UUID, name: str, version: int | None) -> Select[RunArtifact]:
    """The row of that version of the run's artifact `name`, its latest without one."""
    query = select(RunArtifact).where(RunArtifact.run_id == run_id, RunArtifact.name == name)
    if version is not None:
        return query.where(RunArtifact.version == version)
    return query.order_by(RunArtifact.version.desc()).limit(1)


def _artifact(row: RunArtifact) -> Artifact:
    return Artifact(
        name=row.name,
        version=row.version,
        node_id=row.node_id,
        media_type=row.media_type,
        size=row.size,
        sha256=row.sha256,
        content=row.content,
        output_schema=row.output_schema,
    )
