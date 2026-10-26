"""Rerunning a run: a new run with the same workflow spec, input, repo and workspace, linked to
the original by `rerun_of`. The original is never changed (its log is append-only); resuming a
run from its checkpoint is a different, later feature."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import parse_spec
from agentic_store.approvals import RunNotFoundError
from agentic_store.audit import audit, usd
from agentic_store.cancel import ENDED_STATUSES
from agentic_store.models import Run
from agentic_store.policy import run_policy


class RunNotEndedError(Exception):
    """The run has not ended yet; only an ended run can be rerun."""


async def create_rerun(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, budget_usd: Decimal | None = None
) -> UUID:
    """Insert a `queued` copy of the ended run `run_id` (its spec, input, repo, workspace,
    template and template options) with `rerun_of` set to it, and return the new run's id.
    Raises `RunNotFoundError`, or `RunNotEndedError` if the run is still queued, running or
    waiting. The new run gets the workspace's policy as it is now, not the original's, with
    `budget_usd` as its budget if given, and `PolicyViolationError` is raised if the spec is above
    it. The original's spend does not count toward it."""
    new_id = uuid4()
    async with sessions.begin() as session:
        # An ended run never changes again, so it needs no lock while it is copied.
        original = await session.get(Run, run_id)
        if original is None:
            raise RunNotFoundError(f"run {run_id} not found")
        if original.status not in ENDED_STATUSES:
            raise RunNotEndedError(f"run {run_id} has not ended ({original.status})")
        policy = await run_policy(
            session, original.workspace_id, parse_spec(original.spec), budget_usd
        )
        session.add(
            Run(
                id=new_id,
                workspace_id=original.workspace_id,
                status="queued",
                spec=original.spec,
                policy=policy.model_dump(mode="json"),
                input=original.input,
                repo=original.repo,
                repo_url=original.repo_url,
                template_id=original.template_id,
                template_parameters=original.template_parameters,
                rerun_of=original.id,
            )
        )
        audit(
            session,
            original.workspace_id,
            "run.rerun",
            run_id=new_id,
            details={
                "rerun_of": str(original.id),
                "template_id": original.template_id,
                "repo_url": original.repo_url,
                "budget_usd": usd(policy.budget_usd),
            },
        )
    return new_id
