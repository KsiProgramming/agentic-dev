"""`on_review` (7.6): a review comment on the workflow's pull request starts a follow-up from a
top-level step, which must come before the one `github.openPR`, with a gate between them."""

from typing import Any

import pytest
from pydantic import ValidationError

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import WorkflowSpec, validate_workflow
from agentic_engine.templates.sdd import SddParams, build_sdd_spec


def sdd(on_review: object = None) -> dict[str, Any]:
    document = build_sdd_spec(SddParams()).model_dump(mode="json", by_alias=True)
    document["on_review"] = on_review
    return document


def issues(document: dict[str, Any]) -> list[tuple[str, str, str]]:
    found = validate_workflow(
        document, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="claude-x"
    )
    return [(i.code, i.path, i.message) for i in found]


def test_the_sdd_shape_takes_on_review_from_its_review_loop() -> None:
    document = sdd({"from": "review_loop"})
    assert issues(document) == []
    spec = WorkflowSpec.model_validate(document)
    assert spec.on_review is not None and spec.on_review.from_ == "review_loop"
    assert spec.model_dump(mode="json", by_alias=True)["on_review"] == {"from": "review_loop"}


def test_a_workflow_without_on_review_has_none() -> None:
    assert WorkflowSpec.model_validate(sdd()).on_review is None


@pytest.mark.parametrize(
    ("source", "code", "says"),
    [
        ("nowhere", "reference", "is not a node of the workflow"),
        ("engineer", "on_review_invalid", "must be a top-level step"),
        ("publish", "on_review_invalid", "must come before the github.openPR"),
        ("jira_update", "on_review_invalid", "must come before the github.openPR"),
    ],
)
def test_on_review_from_must_be_a_top_level_step_before_the_publish(
    source: str, code: str, says: str
) -> None:
    document = sdd({"from": source})
    [(found_code, path, message)] = issues(document)
    assert (found_code, path) == (code, "on_review.from")
    assert says in message
    with pytest.raises(ValidationError, match=says):
        WorkflowSpec.model_validate(document)


def test_on_review_needs_a_gate_between_from_and_the_publish() -> None:
    # `commit_specs` comes after the loop, but `approve_pr` is the gate: from right after it,
    # nothing is gated. Move the gate before `commit_specs` and start there.
    document = sdd({"from": "commit_specs"})
    steps = document["root"]["steps"]
    ids = [step["id"] for step in steps]
    gate = steps.pop(ids.index("approve_pr"))
    steps.insert(ids.index("commit_specs"), gate)
    # The publish rule complains too (commit_specs now changes the branch after the gate).
    [(_, path, message)] = [i for i in issues(document) if i[0] == "on_review_invalid"]
    assert path == "on_review.from"
    assert "a gate must come between" in message


def test_on_review_needs_exactly_one_publish() -> None:
    document = sdd({"from": "review_loop"})
    steps = document["root"]["steps"]
    steps[:] = [s for s in steps if s["id"] not in {"publish", "jira_update", "move"}]
    [(code, _, message)] = issues(document)
    assert code == "on_review_invalid"
    assert "exactly one github.openPR (it has 0)" in message


def test_set_param_sets_on_review_on_the_document() -> None:
    from agentic_engine.spec.ops import SetParam, apply_ops

    document = sdd()
    changed = apply_ops(
        document,
        [SetParam(op="setParam", path="on_review", value={"from": "review_loop"})],
    )
    assert changed["on_review"] == {"from": "review_loop"}
