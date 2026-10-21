"""Creating and loading runs."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_store.models import Run


@dataclass(frozen=True)
class StoredRun:
    id: UUID
    status: str
    spec: WorkflowSpec
    input: str


async def create_run(
    sessions: async_sessionmaker[AsyncSession], spec: WorkflowSpec, input: str = ""
) -> UUID:
    """Insert a `queued` run holding `spec` and `input`; returns its id."""
    run_id = uuid4()
    async with sessions.begin() as session:
        session.add(Run(id=run_id, status="queued", spec=spec.model_dump(mode="json"), input=input))
    return run_id


async def get_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> StoredRun | None:
    async with sessions() as session:
        run = await session.get(Run, run_id)
    if run is None:
        return None
    return StoredRun(id=run.id, status=run.status, spec=parse_spec(run.spec), input=run.input)
