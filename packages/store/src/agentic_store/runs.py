"""Creating and loading runs."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import WorkflowSpec
from agentic_sandbox import RepoSource
from agentic_store.audit import audit, usd
from agentic_store.jira_triggers import JiraOrigin, add_trigger_run, lock_trigger_issue
from agentic_store.models import DEFAULT_WORKSPACE_ID, Run
from agentic_store.policy import run_policy
from agentic_store.subflows import run_spec


@dataclass(frozen=True)
class RerunFrom:
    """Where a rerun from a step (12.4) starts: the top-level step `node_id` of the run
    `run_id`, with that step's uncommitted work restored if `use_wip`."""

    run_id: UUID
    node_id: str
    use_wip: bool = False


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
    created_at: datetime | None = None
    # The commit its first clone was at (12.2), which its later sandboxes are cloned at.
    base_sha: str | None = None
    # A rerun from a step (12.4) starts there instead of from the beginning.
    rerun_from: RerunFrom | None = None


async def create_run(
    sessions: async_sessionmaker[AsyncSession],
    spec: WorkflowSpec,
    input: str = "",
    repo: RepoSource | None = None,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    template_id: str | None = None,
    template_parameters: dict[str, JsonValue] | None = None,
    budget_usd: Decimal | None = None,
    trigger: str = "api",
    workflow_version: tuple[str, int] | None = None,
    subflows: dict[str, JsonValue] | None = None,
    jira_origin: JiraOrigin | None = None,
) -> UUID:
    """Insert a `queued` run of `workspace_id` holding `spec`, `input` and `repo`, and the
    template `spec` was built from (with its options) or the stored workflow version it was read
    from (`(workflow_id, version)`), if any; returns its id. The workspace must
    exist. `trigger` says who started it (`manual` or `api`). The run gets the workspace's policy
    with `budget_usd` in place of its budget, if given (`run_policy`), which raises
    `PolicyViolationError` if the spec is above it. A spec that calls other workflows is given
    expanded (`agentic_store.subflows.resolve_workflow`) with the copies of what it calls
    (`subflows`), which the run keeps; its stored spec is the one written, without them.

    With `jira_origin` (7.3) the run is a Jira trigger's: its trigger is `jira`, it keeps the rule
    and the issue, and the rule's fire and audit entry are committed with it. It raises
    `TriggerRunActiveError` when the rule already has a run going on the issue."""
    run_id = uuid4()
    async with sessions.begin() as session:
        if jira_origin is not None:
            await lock_trigger_issue(session, jira_origin)
        policy = await run_policy(session, workspace_id, spec, budget_usd)
        run = Run(
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
            workflow_id=workflow_version[0] if workflow_version else None,
            workflow_version=workflow_version[1] if workflow_version else None,
            subflows=subflows or None,
            trigger=trigger,
            branch=repo.ref if repo else None,
        )
        session.add(run)
        audit(
            session,
            workspace_id,
            "run.created",
            run_id=run_id,
            details={
                "template_id": template_id,
                **(
                    {"workflow_id": workflow_version[0], "workflow_version": workflow_version[1]}
                    if workflow_version
                    else {}
                ),
                "repo_url": repo.url if repo else None,
                "budget_usd": usd(policy.budget_usd),
            },
        )
        if jira_origin is not None:
            await session.flush()  # the fire refers to the run; no relationship orders them
            add_trigger_run(session, workspace_id, run, jira_origin)
    return run_id


async def get_run(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> StoredRun | None:
    async with sessions() as session:
        run = await session.get(Run, run_id)
    return None if run is None else stored_run(run)


def stored_run(run: Run) -> StoredRun:
    return StoredRun(
        id=run.id,
        status=run.status,
        spec=run_spec(run.spec, run.subflows),
        input=run.input,
        repo=RepoSource.model_validate(run.repo) if run.repo is not None else None,
        attempt=run.attempt,
        workspace_id=run.workspace_id,
        policy=Policy.model_validate(run.policy),
        spent=run.estimated_usd,
        created_at=run.created_at,
        base_sha=run.base_sha,
        rerun_from=_rerun_from(run),
    )


def _rerun_from(run: Run) -> RerunFrom | None:
    if run.rerun_from is None or run.rerun_of is None:
        return None
    return RerunFrom(
        run_id=run.rerun_of,
        node_id=str(run.rerun_from["node_id"]),
        use_wip=run.rerun_from.get("use_wip") is True,
    )
