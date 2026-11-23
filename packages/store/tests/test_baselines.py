"""What a node usually costs (13.7): the mean per execution over the last 20 completed runs of the
workflow, kept only for nodes that at least 5 of them ran, and frozen on a run at creation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_store import (
    BASELINE_RUNS,
    MIN_RUNS,
    Run,
    RunEventRow,
    Workspace,
    cost_baselines,
    create_run,
    get_run,
)

pytestmark = pytest.mark.integration


def spec() -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "baselines",
            "name": "Baselines",
            "root": {
                "type": "sequence",
                "id": "s",
                "steps": [
                    {"type": "agent", "id": "a", "role": "A", "instructions": "Go."},
                    {"type": "agent", "id": "b", "role": "B", "instructions": "Go."},
                ],
            },
        }
    )


async def new_workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def past_run(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    key: str,
    costs: dict[str, list[float]],
    *,
    age: int = 0,
    status: str = "completed",
) -> UUID:
    """A run of the template `key` that ended `age` minutes ago, whose node `n` executed
    `len(costs[n])` times, each execution spending that much."""
    run_id = await create_run(sessions, spec(), "go", workspace_id=workspace_id, template_id=key)
    seq = 0
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status=status, finished_at=datetime.now(UTC) - timedelta(minutes=age))
        )
        for node, spent in costs.items():
            for usd in spent:
                for event, payload in (("node_started", {}), ("usage", {"estimated_usd": usd})):
                    seq += 1
                    session.add(
                        RunEventRow(
                            run_id=run_id,
                            seq=seq,
                            type=event,
                            node_id=node,
                            payload=payload,
                            created_at=datetime.now(UTC),
                        )
                    )
    return run_id


async def test_the_baseline_is_the_mean_per_execution_of_a_node_from_five_runs(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace = await new_workspace(sessions)
    for i in range(MIN_RUNS):
        # `a` runs once for $0.10; `b` twice, $0.20 and $0.40: a mean of $0.30 per execution.
        await past_run(sessions, workspace, "t", {"a": [0.1], "b": [0.2, 0.4]}, age=i)

    found = await cost_baselines(sessions, workspace, "t", ["a", "b", "c"])

    assert found is not None
    assert found["a"] == {"mean_usd": pytest.approx(0.1), "runs": MIN_RUNS}
    assert found["b"] == {"mean_usd": pytest.approx(0.3), "runs": MIN_RUNS}
    assert "c" not in found  # no run ran it


async def test_a_node_fewer_than_five_runs_ran_has_no_baseline(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace = await new_workspace(sessions)
    for i in range(MIN_RUNS):
        costs = {"a": [0.1]} if i == 0 else {"a": [0.1], "b": [1.0]}
        await past_run(sessions, workspace, "t", costs, age=i)

    found = await cost_baselines(sessions, workspace, "t", ["a", "b"])

    assert found is not None and set(found) == {"a"}


async def test_four_runs_are_too_few_and_only_completed_runs_of_the_same_workflow_count(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace = await new_workspace(sessions)
    for i in range(MIN_RUNS - 1):
        await past_run(sessions, workspace, "t", {"a": [0.1]}, age=i)
    await past_run(sessions, workspace, "t", {"a": [0.1]}, status="failed")
    await past_run(sessions, workspace, "other", {"a": [0.1]})
    other_workspace = await new_workspace(sessions)
    await past_run(sessions, other_workspace, "t", {"a": [0.1]})

    assert await cost_baselines(sessions, workspace, "t", ["a"]) is None
    assert await cost_baselines(sessions, workspace, None, ["a"]) is None


async def test_only_the_last_twenty_completed_runs_are_averaged(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace = await new_workspace(sessions)
    for i in range(BASELINE_RUNS):
        await past_run(sessions, workspace, "t", {"a": [0.1]}, age=i)
    for i in range(3):  # older and dearer: out of the window
        await past_run(sessions, workspace, "t", {"a": [9.0]}, age=1000 + i)

    found = await cost_baselines(sessions, workspace, "t", ["a"])

    assert found is not None
    assert found["a"] == {"mean_usd": pytest.approx(0.1), "runs": BASELINE_RUNS}


async def test_a_new_run_keeps_the_baselines_it_was_created_with(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    workspace = await new_workspace(sessions)
    for i in range(MIN_RUNS):
        await past_run(sessions, workspace, "t", {"a": [0.1]}, age=i)

    run_id = await create_run(sessions, spec(), "go", workspace_id=workspace, template_id="t")
    # Later history moves the average; the run's own line does not move.
    for i in range(MIN_RUNS):
        await past_run(sessions, workspace, "t", {"a": [5.0]}, age=i)
    stored = await get_run(sessions, run_id)
    fresh = await create_run(sessions, spec(), "go", workspace_id=workspace, template_id="t")
    other = await get_run(sessions, fresh)

    assert stored is not None and other is not None
    assert stored.cost_baselines == {"a": {"mean_usd": pytest.approx(0.1), "runs": MIN_RUNS}}
    assert other.cost_baselines is not None
    later = other.cost_baselines["a"]
    assert isinstance(later, dict) and float(later["mean_usd"]) > 0.1
