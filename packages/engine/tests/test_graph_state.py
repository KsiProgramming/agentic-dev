from uuid import uuid4

from agentic_engine.agent import AgentNodeResult, sum_usage
from agentic_engine.graph.state import WorkflowRunResult, initial_state, merge_results
from agentic_runtime import Completed, Message, Usage

DONE = AgentNodeResult(
    status="completed",
    text="hi",
    usage=Usage(input_tokens=1, output_tokens=2),
    events=[Message(text="hi"), Usage(input_tokens=1, output_tokens=2), Completed()],
)


def test_initial_state_seeds_last_text_with_input() -> None:
    assert initial_state("go") == {
        "input": "go",
        "last_text": "go",
        "results": {},
        "order": [],
        "iterations": {},
        "usage": [],
        "map_results": {},
        "spawned": 0,
        "parallel_results": {},
        "artifacts": {},
        "routes": {},
        "plans": {},
        "rounds": {},
    }


def test_merge_results_adds_by_node_id() -> None:
    merged = merge_results({"a": DONE}, {"b": DONE})
    assert list(merged) == ["a", "b"]


def test_sum_usage_skips_none_and_keeps_optional_fields_unset() -> None:
    total = sum_usage(
        [Usage(input_tokens=1, output_tokens=2), None, Usage(input_tokens=3, output_tokens=4)]
    )
    assert total == Usage(input_tokens=4, output_tokens=6)
    assert sum_usage([None]) is None


def test_sum_usage_adds_optional_fields_when_set() -> None:
    total = sum_usage(
        [
            Usage(input_tokens=1, output_tokens=1, estimated_usd=0.5),
            Usage(input_tokens=1, output_tokens=1, premium_requests=1, estimated_usd=0.25),
        ]
    )
    assert total is not None
    assert (total.estimated_usd, total.premium_requests) == (0.75, 1)


def test_sum_usage_adds_cache_tokens_and_keeps_a_shared_model() -> None:
    a = Usage(model="m", input_tokens=1, output_tokens=1, cache_read_tokens=5, cache_write_tokens=2)
    total = sum_usage([a, a])
    assert total == Usage(
        model="m", input_tokens=2, output_tokens=2, cache_read_tokens=10, cache_write_tokens=4
    )
    mixed = sum_usage([a, a.model_copy(update={"model": "other"})])
    assert mixed is not None and mixed.model is None


def test_sum_usage_has_no_cost_when_one_record_is_unpriced() -> None:
    total = sum_usage(
        [
            Usage(input_tokens=1, output_tokens=1, estimated_usd=0.5),
            Usage(input_tokens=1, output_tokens=1),
        ]
    )
    assert total is not None and total.estimated_usd is None


def test_workflow_run_result_round_trips_through_json() -> None:
    result = WorkflowRunResult(
        run_id=uuid4(),
        status="completed",
        text="hi",
        order=["a"],
        results={"a": DONE},
        usage=DONE.usage,
    )
    assert WorkflowRunResult.model_validate_json(result.model_dump_json()) == result
