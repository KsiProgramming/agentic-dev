"""Does a run match the drawn graph (6.8, `agentic_engine.conformance`)? The AC-2 run and every
recorded run fixture match their specs; a trace broken by hand is caught by the rule it breaks;
routes not taken, runs paused at a gate and gates that end the run are not mismatches."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from agentic_engine.conformance import (
    Mismatch,
    events_from_json,
    outcomes,
    trace_mismatches,
)
from agentic_engine.events import RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.spec import Node, parse_spec
from agentic_engine.spec.subflows import expand_root, resolve_from, subflow_key

from .test_ac2 import Ac2Run
from .test_audit_fix import AuditRun

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "fixtures"


def rules(found: list[Mismatch]) -> list[tuple[str, str | None]]:
    return [(m.rule, m.node_id) for m in found]


async def finished_ac2() -> Ac2Run:
    run = Ac2Run()
    await run.to_the_end()
    return run


async def test_the_ac2_run_matches_its_graph() -> None:
    run = await finished_ac2()

    assert trace_mismatches(run.spec.root, run.sink.events, run.spec.id) == []
    assert set(outcomes(run.spec.root, run.sink.events).values()) == {"ran"}


def _original(node: JsonValue, renamed: dict[str, str]) -> JsonValue:
    """A called root as `GET /runs/{id}` returns it, with its nodes' own ids back."""
    if isinstance(node, dict):
        return {
            k: renamed.get(v, v) if k == "id" and isinstance(v, str) else _original(v, renamed)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_original(v, renamed) for v in node]
    return node


def _fixture_root(name: str) -> tuple[Node, str, list[RunEvent]]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    spec = parse_spec(data["spec"])
    # A subflow fixture holds each call's resolved root as `GET /runs/{id}` returns it: the
    # workflows it called are rebuilt from them and resolved as the engine does.
    called: dict[str, JsonValue] = {}
    for call in data.get("calls", {}).values():
        workflow = call["workflow"]
        called[subflow_key(workflow["id"], workflow["version"])] = {
            "spec_version": "0",
            "id": workflow["id"],
            "name": workflow["name"],
            "root": _original(call["root"], call["renamed"]),
        }
    root, _, issues = expand_root(spec.root, resolve_from(called), spec.id)
    assert issues == []
    return root, spec.id, events_from_json(data["events"])


@pytest.mark.parametrize(
    "name",
    [
        "orchestrator-run.json",
        "orchestrator-loop-run.json",
        "audit-fix-run.json",
        "subflow-run.json",
    ],
)
def test_every_recorded_run_matches_its_graph(name: str) -> None:
    root, workflow_id, events = _fixture_root(name)

    assert trace_mismatches(root, events, workflow_id) == []


def test_routes_not_taken_are_not_mismatches() -> None:
    root, _, events = _fixture_root("audit-fix-run.json")

    found = outcomes(root, events)

    assert found["fix_first_report"] == "ran"
    assert found["clean_report"] == "not_taken"


async def test_a_run_paused_at_its_gate_has_not_reached_what_comes_after() -> None:
    run = Ac2Run()
    await run.start()

    assert trace_mismatches(run.spec.root, run.sink.events) == []
    assert outcomes(run.spec.root, run.sink.events)["publish"] == "not_reached"


async def test_a_gate_that_ends_the_run_is_not_a_mismatch() -> None:
    run = AuditRun()
    await run.start()
    await run.decide(GateDecision(decision="reject"))

    assert trace_mismatches(run.spec.root, run.sink.events) == []
    assert outcomes(run.spec.root, run.sink.events)["publish"] == "not_taken"


async def test_a_drawn_node_with_no_event_in_a_completed_run_is_caught() -> None:
    run = await finished_ac2()
    events = [e for e in run.sink.events if e.node_id != "test_analyst"]

    assert rules(trace_mismatches(run.spec.root, events)) == [("no_outcome", "test_analyst")]


async def test_an_event_for_a_node_not_drawn_is_caught() -> None:
    run = await finished_ac2()
    events = [
        e.model_copy(update={"node_id": "ghost"}) if e.node_id == "test_analyst" else e
        for e in run.sink.events
    ]

    found = rules(trace_mismatches(run.spec.root, events))

    assert ("unknown_node", "ghost") in found and ("no_outcome", "test_analyst") in found


async def test_a_branch_that_ends_after_its_parallel_is_caught() -> None:
    run = await finished_ac2()
    joined = next(
        e for e in run.sink.events if e.type == "node_completed" and e.node_id == "explore"
    )
    late = next(
        e for e in run.sink.events if e.type == "node_completed" and e.node_id == "test_analyst"
    )
    events = [e.model_copy(update={"seq": joined.seq}) if e is late else e for e in run.sink.events]
    events = [e.model_copy(update={"seq": late.seq}) if e is joined else e for e in events]

    assert ("outside_container", "test_analyst") in rules(trace_mismatches(run.spec.root, events))


async def test_a_step_that_starts_before_the_one_before_it_ended_is_caught() -> None:
    run = await finished_ac2()
    loop_done = next(
        e for e in run.sink.events if e.type == "node_completed" and e.node_id == "review_loop"
    )
    gate_start = next(
        e for e in run.sink.events if e.type == "node_started" and e.node_id == "approve_pr"
    )
    events = [
        e.model_copy(update={"seq": gate_start.seq})
        if e is loop_done
        else e.model_copy(update={"seq": loop_done.seq})
        if e is gate_start
        else e
        for e in run.sink.events
    ]

    assert ("order", "approve_pr") in rules(trace_mismatches(run.spec.root, events))


async def test_loop_iterations_out_of_order_are_caught() -> None:
    run = await finished_ac2()
    events = [
        e.model_copy(update={"payload": {**e.payload, "iteration": 3}})
        if e.type == "loop_iteration_started" and e.payload.get("iteration") == 2
        else e
        for e in run.sink.events
    ]

    assert ("loop_iterations", "review_loop") in rules(trace_mismatches(run.spec.root, events))


async def test_a_run_of_another_workflow_is_caught() -> None:
    run = await finished_ac2()

    found = trace_mismatches(run.spec.root, run.sink.events, "something-else")

    assert rules(found) == [("workflow", None)]
    assert "'plan-build-review'" in found[0].message
