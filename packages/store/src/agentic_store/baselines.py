"""What each node of a workflow usually costs (13.7), for the cost circuit breaker.

The baseline of a node is the mean cost of one execution of it over the last `BASELINE_RUNS`
completed runs of the same workflow: the template's id, or the stored workflow's id at any version.
A node counts only once `MIN_RUNS` of those runs ran it; until then the breaker does not watch it.
The baselines are worked out when a run is created and stored on it (`runs.cost_baselines`), so a
resume never moves the line.
"""

from collections.abc import Collection
from decimal import Decimal
from typing import Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import NODE_STARTED
from agentic_store.models import Run, RunEventRow

BASELINE_RUNS: Final = 20
"""How many completed runs of the workflow the average is taken over."""
MIN_RUNS: Final = 5
"""How many of them must have run a node for it to have a baseline."""


async def cost_baselines(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    workflow_key: str | None,
    node_ids: Collection[str],
) -> dict[str, JsonValue] | None:
    """`{node_id: {"mean_usd": float, "runs": int}}` for the nodes of `node_ids` that at least
    `MIN_RUNS` of the last `BASELINE_RUNS` completed runs of `workflow_key` ran; `None` when there
    is none."""
    async with sessions() as session:
        return await baselines_in(session, workspace_id, workflow_key, node_ids)


async def baselines_in(
    session: AsyncSession,
    workspace_id: UUID,
    workflow_key: str | None,
    node_ids: Collection[str],
) -> dict[str, JsonValue] | None:
    """`cost_baselines` inside the caller's session."""
    if workflow_key is None or not node_ids:
        return None
    ids = (
        await session.scalars(
            select(Run.id)
            .where(
                Run.workspace_id == workspace_id,
                Run.status == "completed",
                func.coalesce(Run.template_id, Run.workflow_id) == workflow_key,
            )
            .order_by(Run.finished_at.desc().nulls_last(), Run.created_at.desc())
            .limit(BASELINE_RUNS)
        )
    ).all()
    if len(ids) < MIN_RUNS:
        return None
    spent = cast(RunEventRow.payload["estimated_usd"].astext, Numeric)
    costs = {
        (run_id, node): total or Decimal(0)
        for run_id, node, total in (
            await session.execute(
                select(RunEventRow.run_id, RunEventRow.node_id, func.sum(spent))
                .where(
                    RunEventRow.run_id.in_(ids),
                    RunEventRow.type == "usage",
                    RunEventRow.node_id.in_(node_ids),
                )
                .group_by(RunEventRow.run_id, RunEventRow.node_id)
            )
        ).all()
    }
    started = (
        await session.execute(
            select(RunEventRow.run_id, RunEventRow.node_id, func.count())
            .where(
                RunEventRow.run_id.in_(ids),
                RunEventRow.type == NODE_STARTED,
                RunEventRow.node_id.in_(node_ids),
            )
            .group_by(RunEventRow.run_id, RunEventRow.node_id)
        )
    ).all()
    runs: dict[str, int] = {}
    executions: dict[str, int] = {}
    total: dict[str, Decimal] = {}
    for run_id, node, count in started:
        assert node is not None
        runs[node] = runs.get(node, 0) + 1
        executions[node] = executions.get(node, 0) + count
        total[node] = total.get(node, Decimal(0)) + costs.get((run_id, node), Decimal(0))
    found: dict[str, JsonValue] = {
        node: {"mean_usd": float(total[node] / executions[node]), "runs": n}
        for node, n in sorted(runs.items())
        if n >= MIN_RUNS
    }
    return found or None
