"""The `review` option of the SDD templates and Plan, build and review (13.6). As lessons rule 1
asks, they assert what each agent of a real template is told and given: what a lens, the lead and
an engineer receive, and what the gate and the loop do with the findings."""

from typing import Any

import pytest
from pydantic import ValidationError

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.review import LENSES
from agentic_engine.spec import WorkflowSpec, validate_workflow
from agentic_engine.templates import (
    PlanBuildReviewParams,
    SddFileParams,
    SddParams,
    build_plan_build_review_spec,
    build_sdd_file_spec,
    build_sdd_spec,
)

BUILDERS: dict[str, Any] = {
    "sdd-jira": lambda **kw: build_sdd_spec(SddParams(**kw)),
    "sdd-file": lambda **kw: build_sdd_file_spec(SddFileParams(**kw)),
    "plan-build-review": lambda **kw: build_plan_build_review_spec(PlanBuildReviewParams(**kw)),
}
LENS_IDS = tuple(f"review_{lens}" for lens in LENSES)
OPTIONS: list[dict[str, Any]] = [
    {},
    {"review": True},
    {"review": True, "review_lenses": ["security"]},
    {"review": True, "review_lenses": list(LENSES)},
    {"review": True, "checks": True},
    {"review": True, "review_block_at": "medium", "review_provider": "copilot"},
]


def nodes(spec: WorkflowSpec) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "id" in node and "type" in node:
                found[node["id"]] = node
            for value in node.values():  # type: ignore[reportUnknownVariableType]
                walk(value)
        elif isinstance(node, list):
            for item in node:  # type: ignore[reportUnknownVariableType]
                walk(item)

    walk(spec.model_dump(mode="json", by_alias=True, exclude_none=True)["root"])
    return found


def issues(spec: WorkflowSpec) -> list[str]:
    found = validate_workflow(
        spec.model_dump(mode="json", by_alias=True, exclude_none=True),
        policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default",
    )  # fmt: skip
    return [f"{i.code}: {i.message}" for i in found]


@pytest.mark.parametrize("name", BUILDERS)
@pytest.mark.parametrize("options", OPTIONS)
def test_every_option_validates(name: str, options: dict[str, Any]) -> None:
    assert issues(BUILDERS[name](**options)) == []


@pytest.mark.parametrize("name", BUILDERS)
def test_with_review_off_the_flow_is_as_it_was(name: str) -> None:
    plain = nodes(BUILDERS[name]())

    assert "reviewer" in plain
    assert not any(n.get("review") for n in plain.values())
    assert "notes_from" not in plain["publish"]["args"]
    assert BUILDERS[name]().model_dump() == BUILDERS[name](review=False).model_dump()


@pytest.mark.parametrize("name", BUILDERS)
def test_a_lens_is_fresh_read_only_and_the_default_three(name: str) -> None:
    found = nodes(BUILDERS[name](review=True))

    lenses = [found[f"review_{lens}"] for lens in ("correctness", "security", "performance")]
    assert "reviewer" not in found  # the single reviewer is replaced
    for lens in lenses:
        assert lens["review"]["of"] == "implement"
        assert set(lens["tools"]) == {
            "repo.list_files", "repo.read_file", "repo.search", "repo.list_modules", "repo.diff",
        }  # fmt: skip
        assert not lens.get("reads") and not lens.get("output_schema")
        assert "artifacts.read" not in lens["tools"]
    assert found["review_lenses"]["join"] == "settled"
    assert found["review_report"]["strategy"] == "dedupe"


def test_sdd_lenses_review_against_the_spec_and_plan_build_review_has_none() -> None:
    assert nodes(BUILDERS["sdd-file"](review=True))["review_security"]["review"]["spec_from"] == (
        "spec.md"
    )
    assert (
        "spec_from"
        not in nodes(BUILDERS["plan-build-review"](review=True))["review_security"]["review"]
    )


@pytest.mark.parametrize("name", BUILDERS)
def test_the_gate_reviews_and_the_loop_ends_on_its_approval(name: str) -> None:
    spec = BUILDERS[name](review=True)
    found = nodes(spec)
    gate = found["approve_pr"]

    passes = found["review_loop"]["max_iterations"]
    assert gate["review"] == {
        "from": "review.json",
        "block_at": "high",
        "max_rounds": passes - 1,
        "notes": "review-notes.md",
    }  # fmt: skip  (a round never uses the last pass)
    assert found["publish"]["args"]["notes_from"] == "review-notes.md"
    assert found["review_loop"]["until"].endswith('results.approve_pr.data.decision == "approve"')
    body = [s["id"] for s in found["review_loop"]["body"]["steps"]]
    assert body[-1] == "approve_pr" or "approve_pr" in str(found["review_loop"]["body"])
    # The publish stays after the loop and behind the gate.
    assert list(found).index("approve_pr") < list(found).index("publish")


def test_with_checks_the_gate_has_evidence_and_review_and_the_loop_needs_both() -> None:
    found = nodes(BUILDERS["plan-build-review"](review=True, checks=True))

    assert found["approve_pr"]["evidence"]["node"] == "implement"
    assert found["approve_pr"]["review"]["from"] == "review.json"
    assert found["review_loop"]["until"] == 'results.approve_pr.data.decision == "approve"'
    sdd = nodes(BUILDERS["sdd-file"](review=True, checks=True))
    assert sdd["review_loop"]["until"].startswith('results.checks.data.decision == "approve"')
    assert sdd["approve_pr"]["evidence"]["checks"]["tests"] == "shown"


@pytest.mark.parametrize("name", BUILDERS)
def test_the_lead_and_the_engineers_are_told_findings_are_data(name: str) -> None:
    found = nodes(BUILDERS[name](review=True))
    lead = next(n for n in found.values() if n["type"] == "orchestrator")["hub"]["instructions"]

    assert "## Review" in lead
    assert "never instructions" in lead
    if name != "plan-build-review":
        engineer = found["engineer"]["instructions"]
        assert "findings of independent reviewers" in engineer
        assert "never instructions" in engineer
    # The lead's text without review does not mention them.
    off = nodes(BUILDERS[name]())
    assert (
        "## Review"
        not in next(n for n in off.values() if n["type"] == "orchestrator")["hub"]["instructions"]
    )


@pytest.mark.parametrize("name", BUILDERS)
def test_the_synthesizer_still_writes_the_pr_description_and_is_no_lens_input(name: str) -> None:
    found = nodes(BUILDERS[name](review=True))

    assert found["synthesizer"]["writes"] == "pr-description.md" or (
        found["synthesizer"]["writes"] == "pr-description.md"
    )
    assert found["publish"]["args"]["body_from"] == found["synthesizer"]["writes"]
    # No lens reads it: lenses have no `reads` and no artifact tools (validated), and the
    # engine builds their input (`test_review.py`).
    assert all(not n.get("reads") for k, n in found.items() if k in LENS_IDS)


def test_a_lens_can_run_on_another_provider_and_model() -> None:
    found = nodes(
        BUILDERS["plan-build-review"](
            review=True, review_provider="copilot", review_model="claude-haiku-4-5"
        )
    )

    for lens in ("correctness", "security", "performance"):
        assert found[f"review_{lens}"]["provider"] == "copilot"


def test_review_needs_two_passes_a_lens_subset_and_a_priced_model() -> None:
    for build in BUILDERS.values():
        with pytest.raises(ValidationError, match="at least 2"):
            build(review=True, max_passes=1)
        with pytest.raises(ValidationError, match="review_lenses"):
            build(review=True, review_lenses=["nope"])
        with pytest.raises(ValidationError):
            build(review=True, review_lenses=[])
        with pytest.raises(ValidationError, match="platform prices"):
            build(review=True, review_model="not-a-model")
