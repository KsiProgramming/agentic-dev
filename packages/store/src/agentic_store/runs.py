"""Creating and loading runs."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import RepoSource
from agentic_store.models import DEFAULT_WORKSPACE_ID, Run


@dataclass(frozen=True)
class StoredRun:
    id: UUID
    status: str
    spec: WorkflowSpec
    input: str
    repo: RepoSource | None = None
    # How many times a worker has claimed the run; above 1 it is being resumed.
    attempt: int = 0
    workspace_id: UUID = DEFAULT_WORKSPACE_ID


async def create_run(
    sessions: async_sessionmaker[AsyncSession],
    spec: WorkflowSpec,
    input: str = "",
    repo: RepoSource | None = None,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    template_id: str | None = None,
    template_parameters: dict[str, JsonValue] | None = None,
) -> UUID:
    """Insert a `queued` run of `workspace_id` holding `spec`, `input` and `repo`, and the
    template `spec` was built from (with its options) if any; returns its id. The workspace must
    exist."""
    run_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            Run(
                id=run_id,
                workspace_id=workspace_id,
                status="queued",
                spec=spec.model_dump(mode="json"),
                input=input,
                repo=repo.model_dump(mode="json") if repo else None,
                repo_url=repo.url if repo else None,
                template_id=template_id,
                template_parameters=template_parameters,
            )
        )
    return run_id


async def get_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> StoredRun | None:
    async with sessions() as session:
        run = await session.get(Run, run_id)
    return None if run is None else stored_run(run)


def stored_run(run: Run) -> StoredRun:
    return StoredRun(
        id=run.id,
        status=run.status,
        spec=parse_spec(run.spec),
        input=run.input,
        repo=RepoSource.model_validate(run.repo) if run.repo is not None else None,
        attempt=run.attempt,
        workspace_id=run.workspace_id,
    )
