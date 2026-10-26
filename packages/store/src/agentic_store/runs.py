"""Creating and loading runs."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import RepoSource
from agentic_store.audit import audit, usd
from agentic_store.models import DEFAULT_WORKSPACE_ID, Run
from agentic_store.policy import run_policy


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
    # The limits the run got when it was created.
    policy: Policy = PLATFORM_POLICY
    # USD the run's usage has cost so far, for its budget.
    spent: Decimal = Decimal(0)


async def create_run(
    sessions: async_sessionmaker[AsyncSession],
    spec: WorkflowSpec,
    input: str = "",
    repo: RepoSource | None = None,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    template_id: str | None = None,
    template_parameters: dict[str, JsonValue] | None = None,
    budget_usd: Decimal | None = None,
) -> UUID:
    """Insert a `queued` run of `workspace_id` holding `spec`, `input` and `repo`, and the
    template `spec` was built from (with its options) if any; returns its id. The workspace must
    exist. The run gets the workspace's policy with `budget_usd` in place of its budget, if given
    (`run_policy`), which raises `PolicyViolationError` if the spec is above it."""
    run_id = uuid4()
    async with sessions.begin() as session:
        policy = await run_policy(session, workspace_id, spec, budget_usd)
        session.add(
            Run(
                id=run_id,
                workspace_id=workspace_id,
                status="queued",
                spec=spec.model_dump(mode="json"),
                policy=policy.model_dump(mode="json"),
                input=input,
                repo=repo.model_dump(mode="json") if repo else None,
                repo_url=repo.url if repo else None,
                template_id=template_id,
                template_parameters=template_parameters,
            )
        )
        audit(
            session,
            workspace_id,
            "run.created",
            run_id=run_id,
            details={
                "template_id": template_id,
                "repo_url": repo.url if repo else None,
                "budget_usd": usd(policy.budget_usd),
            },
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
        policy=Policy.model_validate(run.policy),
        spent=run.estimated_usd,
    )
