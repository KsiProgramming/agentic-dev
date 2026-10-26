"""A workspace's run limits: the platform policy (`agentic_engine.policy.PLATFORM_POLICY`) with
the workspace's own, lower limits on top. A run gets the effective policy when it is created and
keeps it, so changing the workspace's limits never changes a run that already exists."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import GATE_WAITING, RUN_RESUMED, RUN_STARTED
from agentic_engine.policy import Policy, PolicyOverrides, effective_policy, with_budget
from agentic_engine.spec import (
    ValidationIssue,
    WorkflowSpec,
    budget_issues,
    messages,
    policy_issues,
    validate_workflow,
)
from agentic_runtime.claude import DEFAULT_MODEL
from agentic_store.audit import audit
from agentic_store.connections import WorkspaceNotFoundError
from agentic_store.models import RunEventRow, Workspace, WorkspacePolicy
from agentic_store.pricing import price_table


class PolicyViolationError(Exception):
    """The workflow cannot run under the workspace's policy; `issues` says why, one per problem,
    and `errors` says it for people."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        self.errors = messages(issues)
        super().__init__("; ".join(self.errors))


async def get_policy_overrides(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> PolicyOverrides:
    """The workspace's own limits. Raises `WorkspaceNotFoundError`."""
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        return await _overrides(session, workspace_id)


async def replace_policy_overrides(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, overrides: PolicyOverrides
) -> None:
    """Make `overrides` the workspace's own limits; all `None` resets it to the platform policy.
    Raises `WorkspaceNotFoundError`."""
    async with sessions.begin() as session:
        workspace = await session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        before = await _overrides(session, workspace_id)
        if before != overrides:
            audit(
                session,
                workspace_id,
                "policy.updated",
                details={
                    "before": before.model_dump(mode="json"),
                    "after": overrides.model_dump(mode="json"),
                },
            )
        row = await session.get(WorkspacePolicy, workspace_id)
        if row is None:
            row = WorkspacePolicy(workspace_id=workspace_id)
            session.add(row)
        for name, value in overrides.model_dump().items():
            setattr(row, name, value)
        row.updated_at = datetime.now(UTC)


async def run_policy(
    session: AsyncSession,
    workspace_id: UUID,
    spec: WorkflowSpec,
    budget_usd: Decimal | None = None,
) -> Policy:
    """The policy a new run of `spec` in the workspace gets, with the run's own `budget_usd` in
    place of the workspace's if it set one. Raises `PolicyViolationError` if the spec is above
    it, or if it has a budget and an agent's model has no price in the workspace (an agent with
    no `model` runs on the platform's default)."""
    policy = with_budget(effective_policy(await _overrides(session, workspace_id)), budget_usd)
    issues = policy_issues(spec.root, policy)
    if policy.budget_usd is not None:
        prices = await price_table(session, workspace_id)
        issues += budget_issues(spec.root, policy, prices.__contains__, DEFAULT_MODEL)
    if issues:
        raise PolicyViolationError(issues)
    return policy


async def check_workflow(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    raw: object,
    budget_usd: Decimal | None = None,
) -> tuple[Policy, list[ValidationIssue]]:
    """Why the decoded workflow document `raw` could not run in the workspace now
    (`validate_workflow`), with the policy a run of it would get: the workspace's, with
    `budget_usd` in place of its budget if given. Writes nothing. Raises
    `WorkspaceNotFoundError`."""
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        overrides = await _overrides(session, workspace_id)
        prices = await price_table(session, workspace_id)
    policy = with_budget(effective_policy(overrides), budget_usd)
    issues = validate_workflow(
        raw, policy=policy, priced=prices.__contains__, default_model=DEFAULT_MODEL
    )
    return policy, issues


async def active_seconds(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> float:
    """How long the run has spent executing so far, for its `wall_time_s` limit, from its event
    log: each stretch from `run_started` or `run_resumed` to `gate_waiting` or the attempt's last
    event. Time paused at a gate, and the gap between a crashed attempt's last event and the next
    attempt, do not count."""
    events = (
        select(
            RunEventRow.type,
            RunEventRow.created_at,
            func.lag(RunEventRow.created_at).over(order_by=RunEventRow.seq).label("before"),
        )
        .where(RunEventRow.run_id == run_id)
        .subquery()
    )
    async with sessions() as session:
        boundaries = (
            await session.execute(
                select(events.c.type, events.c.created_at, events.c.before).where(
                    events.c.type.in_((RUN_STARTED, RUN_RESUMED, GATE_WAITING))
                )
            )
        ).all()
        last = await session.scalar(
            select(func.max(RunEventRow.created_at)).where(RunEventRow.run_id == run_id)
        )
    total, start = 0.0, None
    for type, at, before in boundaries:
        if type == GATE_WAITING:
            if start is not None:
                total += (at - start).total_seconds()
            start = None
        else:
            if start is not None and before is not None:
                # The earlier attempt was cut off: it ran until its last event.
                total += (before - start).total_seconds()
            start = at
    if start is not None and last is not None:
        total += (last - start).total_seconds()
    return total


async def _overrides(session: AsyncSession, workspace_id: UUID) -> PolicyOverrides:
    row = await session.scalar(
        select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == workspace_id)
    )
    if row is None:
        return PolicyOverrides()
    return PolicyOverrides(
        agents_alive=row.agents_alive,
        agents_spawned=row.agents_spawned,
        max_depth=row.max_depth,
        loop_iterations=row.loop_iterations,
        wall_time_s=row.wall_time_s,
        budget_usd=row.budget_usd,
    )
