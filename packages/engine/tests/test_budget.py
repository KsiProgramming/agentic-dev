"""The optional budget: a run with one stops cleanly once its spend reaches it, and a run without
one is not capped (phase 3.3)."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.budget import BudgetMeter, budget_meter
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.policy import (
    PLATFORM_POLICY,
    Policy,
    PolicyLimitExceeded,
    PolicyOverrides,
    effective_policy,
    format_usd,
    with_budget,
)
from agentic_engine.spec import WorkflowSpec, budget_errors, parse_spec
from agentic_runtime import Message, Usage
from agentic_runtime.fake import Delay, FakeRuntime, Step


def agent(id: str, model: str | None = None) -> dict[str, object]:
    node: dict[str, object] = {"type": "agent", "id": id, "role": "R", "instructions": "Go."}
    if model is not None:
        node["model"] = model
    return node


def spec(root: object) -> WorkflowSpec:
    return parse_spec({"spec_version": "0", "id": "budget", "name": "Budget", "root": root})


def budgeted(usd: str) -> Policy:
    return with_budget(PLATFORM_POLICY, Decimal(usd))


def costing(usd: float | None, *, then: float = 0.0) -> list[Step]:
    """An agent turn that reports one usage priced `usd` (no price if `None`), then takes `then`
    seconds before it ends."""
    return [
        Usage(model="m", input_tokens=1, output_tokens=1, estimated_usd=usd),
        Delay(then),
        Message(text="done"),
    ]


def lifecycle(events: list[RunEvent]) -> list[tuple[str, str | None]]:
    return [(e.type, e.node_id) for e in events if e.type.startswith(("node_", "run_", "policy_"))]


def stop_of(events: list[RunEvent]) -> RunEvent:
    [stop] = [e for e in events if e.type == "policy_limit_exceeded"]
    return stop


# The policy and the meter


def test_a_workspace_budget_is_a_default_a_run_may_replace() -> None:
    workspace = effective_policy(PolicyOverrides(budget_usd=Decimal("2")))

    assert PLATFORM_POLICY.budget_usd is None
    assert workspace.budget_usd == Decimal("2")
    assert with_budget(workspace, Decimal("5")).budget_usd == Decimal("5")
    assert with_budget(workspace, None) == workspace
    # Frozen on the run as JSON; a run created before 3.3 has no budget.
    assert Policy.model_validate(workspace.model_dump(mode="json")) == workspace
    assert (
        Policy.model_validate(
            {k: v for k, v in PLATFORM_POLICY.model_dump().items() if k != "budget_usd"}
        )
        == PLATFORM_POLICY
    )


def test_a_budget_is_above_zero() -> None:
    with pytest.raises(ValueError):
        PolicyOverrides(budget_usd=Decimal(0))


def test_budget_reasons_name_the_budget_and_the_spend() -> None:
    reached = PolicyLimitExceeded("budget_usd", Decimal("5"), Decimal("5.03"), "writer")
    unpriced = PolicyLimitExceeded(
        "budget_usd", Decimal("0.01"), Decimal("0"), "writer", unpriced_model="x"
    )

    assert reached.reason == "policy limit: budget of $5.00 reached ($5.03 spent)"
    assert reached.payload() == {"limit": "budget_usd", "value": "5", "observed": "5.03"}
    assert unpriced.reason == (
        "policy limit: budget of $0.01 cannot be enforced: model 'x' has no price"
    )
    assert unpriced.payload()["model"] == "x"
    assert [format_usd(Decimal(a)) for a in ("5", "12.346", "0.01", "0.01034567", "0.5")] == [
        "$5.00",
        "$12.35",
        "$0.01",
        "$0.0103",
        "$0.50",
    ]


def test_the_meter_stops_at_exactly_the_budget() -> None:
    meter = BudgetMeter(Decimal("0.3"), spent=Decimal("0.1"))
    meter.add(Usage(input_tokens=1, output_tokens=1, estimated_usd=0.1), "a")

    with pytest.raises(PolicyLimitExceeded) as stop:
        meter.add(Usage(input_tokens=1, output_tokens=1, estimated_usd=0.1), "b")

    assert stop.value.observed == Decimal("0.3")
    assert stop.value.node_id == "b"
    assert budget_meter(PLATFORM_POLICY) is None


# Checks before the run


def test_every_agent_needs_a_priced_model_under_a_budget() -> None:
    workflow = spec(
        {
            "type": "sequence",
            "id": "s",
            "steps": [
                agent("a"),
                agent("b", model="unknown-model"),
                {
                    "type": "map",
                    "id": "m",
                    "over": "['x']",
                    "max_concurrency": 1,
                    "body": agent("c", model="priced"),
                },
                {
                    "type": "reduce",
                    "id": "r",
                    "from": "m",
                    "strategy": "agent",
                    "agent": {"role": "R", "instructions": "Go.", "model": "nope"},
                },
            ],
        }
    )

    def priced(model: str) -> bool:
        return model in {"default", "priced"}

    assert budget_errors(workflow.root, budgeted("1"), priced, "default") == [
        "agent 'b' at root.steps[1]: model 'unknown-model' has no price, so the budget cannot "
        "be enforced",
        "reduce 'r' at root.steps[3]: model 'nope' has no price, so the budget cannot be enforced",
    ]
    assert budget_errors(workflow.root, PLATFORM_POLICY, priced, "default") == []


# Enforcement while the run executes


async def test_a_sequence_stops_once_its_spend_reaches_the_budget() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"a": costing(0.6), "b": costing(0.6), "c": costing(0.6)})
    workflow = spec({"type": "sequence", "id": "s", "steps": [agent("a"), agent("b"), agent("c")]})

    result = await run_workflow(workflow, runtime, sink=sink, policy=budgeted("1"))

    assert result.status == "failed"
    assert result.stopped_at == "b"
    assert [r.node_id for r in runtime.requests] == ["a", "b"]
    assert lifecycle(sink.events) == [
        ("run_started", None),
        ("node_started", "a"),
        ("node_completed", "a"),
        ("node_started", "b"),
        ("node_cancelled", "b"),
        ("policy_limit_exceeded", "b"),
        ("run_failed", None),
    ]
    assert stop_of(sink.events).payload == {
        "limit": "budget_usd",
        "value": "1",
        "observed": "1.2",
    }
    assert sink.events[-1].payload == {
        "error": "policy limit: budget of $1.00 reached ($1.20 spent)"
    }


async def test_spend_exactly_at_the_budget_stops_the_run() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"a": costing(0.5), "b": costing(0.5), "c": costing(0.5)})
    workflow = spec({"type": "sequence", "id": "s", "steps": [agent("a"), agent("b"), agent("c")]})

    result = await run_workflow(workflow, runtime, sink=sink, policy=budgeted("1"))

    assert result.status == "failed"
    assert [r.node_id for r in runtime.requests] == ["a", "b"]
    assert stop_of(sink.events).payload["observed"] == "1"


async def test_a_map_item_over_the_budget_cancels_its_running_siblings() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"w": costing(0.5, then=5)})
    workflow = spec(
        {
            "type": "map",
            "id": "m",
            "over": "['x', 'y', 'z']",
            "max_concurrency": 3,
            "body": agent("w"),
        }
    )
    before = asyncio.all_tasks()

    result = await asyncio.wait_for(
        run_workflow(workflow, runtime, sink=sink, policy=budgeted("1.2")), 2
    )

    assert result.status == "failed"
    ends = [e.type for e in sink.events if e.node_id == "w" and e.type != "node_started"]
    assert [t for t in ends if t.startswith("node_")] == ["node_cancelled"] * 3
    assert not [e for e in sink.events if e.type == "map_item_completed"]
    assert [e.type for e in sink.events[-2:]] == ["policy_limit_exceeded", "run_failed"]
    assert asyncio.all_tasks() <= before


async def test_unpriced_usage_under_a_budget_stops_the_run() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"a": costing(None)})
    workflow = spec({"type": "sequence", "id": "s", "steps": [agent("a"), agent("b")]})

    result = await run_workflow(workflow, runtime, sink=sink, policy=budgeted("1"))

    assert result.status == "failed"
    assert stop_of(sink.events).payload == {
        "limit": "budget_usd",
        "value": "1",
        "observed": "0",
        "model": "m",
    }


async def test_a_run_that_already_spent_its_budget_stops_before_any_node() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime()
    workflow = spec(agent("a"))

    result = await run_workflow(
        workflow, runtime, sink=sink, policy=budgeted("1"), spent=Decimal("1")
    )

    assert result.status == "failed"
    assert runtime.requests == []
    assert lifecycle(sink.events) == [
        ("run_started", None),
        ("policy_limit_exceeded", None),
        ("run_failed", None),
    ]


async def test_spend_before_a_gate_counts_when_the_run_resumes() -> None:
    run_id, checkpointer = uuid4(), InMemorySaver(serde=checkpoint_serde())
    workflow = spec(
        {
            "type": "sequence",
            "id": "s",
            "steps": [agent("a"), {"type": "gate", "id": "g", "title": "OK?"}, agent("b")],
        }
    )
    runtime = FakeRuntime({"a": costing(0.6), "b": costing(0.6)})
    sink = InMemoryEventSink()
    paused = await run_workflow(
        workflow,
        runtime,
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        policy=budgeted("1"),
    )
    assert paused.status == "waiting"

    result = await resume_workflow(
        workflow,
        runtime,
        run_id=run_id,
        sink=sink,
        checkpointer=checkpointer,
        next_seq=len(sink.events) + 1,
        attempt=2,
        decision=GateDecision(decision="approve"),
        policy=budgeted("1"),
        spent=Decimal("0.6"),
    )

    assert result.status == "failed"
    assert result.stopped_at == "b"
    assert stop_of(sink.events).payload["observed"] == "1.2"
    assert sink.events[-1].type == "run_failed"


async def test_an_unbudgeted_run_is_not_capped_and_reports_its_cost() -> None:
    sink = InMemoryEventSink()
    runtime = FakeRuntime({"a": costing(60), "b": costing(60)})
    workflow = spec({"type": "sequence", "id": "s", "steps": [agent("a"), agent("b")]})

    result = await run_workflow(workflow, runtime, sink=sink)

    assert result.status == "completed"
    assert result.usage is not None and result.usage.estimated_usd == 120
    assert not [e for e in sink.events if e.type == "policy_limit_exceeded"]
