import json
from pathlib import Path

import pytest

from agentic_engine.graph import compile_workflow
from agentic_engine.graph.compile import agent_nodes
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime.fake import FakeRuntime

FIXTURES = Path(__file__).parent / "fixtures" / "specs" / "valid"


def load(name: str) -> WorkflowSpec:
    return parse_spec(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("two-step-sequence.json", ["writer", "reviewer"]),
        ("nested-sequence.json", ["planner", "implementer", "tester"]),
    ],
)
def test_sequences_flatten_depth_first(fixture: str, expected: list[str]) -> None:
    assert [n.id for n in agent_nodes(load(fixture).root)] == expected


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("two-step-sequence.json", {"writer", "reviewer"}),
        ("nested-sequence.json", {"planner", "implementer", "tester"}),
    ],
)
def test_graph_nodes_are_named_by_agent_id(fixture: str, expected: set[str]) -> None:
    graph = compile_workflow(load(fixture), FakeRuntime()).get_graph()
    assert set(graph.nodes) == expected | {"__start__", "__end__"}


def test_single_agent_compiles_to_one_node() -> None:
    spec = load("single-agent.json")
    graph = compile_workflow(spec, FakeRuntime()).get_graph()
    assert set(graph.nodes) == {spec.root.id, "__start__", "__end__"}
