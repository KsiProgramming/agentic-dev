"""The "Plan, build and review" template (6.8): AC-2's flow (a parallel, an orchestrator in a
review loop, a gate and a pull request). It validates for every option, only the engineers write,
only `publish` publishes and it comes after the gate, and every agent that checks code reads it
(lessons rules 3, 4 and the rules for writing workflows).

`tests/fixtures/specs/valid/ac2-plan-build-review.json` is the template's default spec; set
`UPDATE_FIXTURES=1` to write it again after a deliberate change."""

import itertools
import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    PUBLISH_TOOLS,
    READ_TOOLS,
    WRITE_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    OrchestratorNode,
    ParallelNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
    node_tools,
    validate_workflow,
)
from agentic_engine.templates import (
    PlanBuildReviewParams,
    build_plan_build_review_spec,
    get_template,
)
from agentic_engine.templates.plan_build_review import MAX_PASSES, MODELS, VERDICT_SCHEMA

FIXTURE = Path(__file__).parent / "fixtures" / "specs" / "valid" / "ac2-plan-build-review.json"
STARTER = "Describe what this agent does."


def _nodes(spec: WorkflowSpec) -> dict[str, Any]:
    return {node.id: node for _, node in iter_nodes(spec.root)}


def _issues(spec: WorkflowSpec) -> list[str]:
    raw = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    issues = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="claude-sonnet-5-5"
    )
    return [issue.message for issue in issues]


def test_the_template_is_registered() -> None:
    template = get_template("plan-build-review")

    assert template is not None
    assert template.requires == ("claude", "github")
    schema = template.parameters_schema()
    assert list(schema["properties"]) == [
        "max_passes", "analyst_model", "engineer_model", "reviewer_model",
    ]  # fmt: skip
    assert "$defs" not in schema
    assert "pull request after you approve" in template.description


@pytest.mark.parametrize(
    ("passes", "model"),
    list(itertools.product(range(1, MAX_PASSES + 1), [None, MODELS[0]])),
)
def test_every_option_validates(passes: int, model: str | None) -> None:
    params = PlanBuildReviewParams(
        max_passes=passes, analyst_model=model, engineer_model=model, reviewer_model=model
    )
    spec = build_plan_build_review_spec(params)

    assert _issues(spec) == []
    loop = _nodes(spec)["review_loop"]
    assert isinstance(loop, LoopNode) and loop.max_iterations == passes
    if model is not None:
        hub = _nodes(spec)["implement"].hub
        assert hub.model == model
        assert {n.model for n in _nodes(spec).values() if isinstance(n, AgentNode)} == {model}


def test_an_unpriced_model_or_too_many_passes_is_refused() -> None:
    with pytest.raises(ValidationError):
        PlanBuildReviewParams(engineer_model="gpt-9")
    with pytest.raises(ValidationError):
        PlanBuildReviewParams(max_passes=MAX_PASSES + 1)


def test_it_has_every_ac2_primitive_in_the_one_order_the_rules_allow() -> None:
    spec = build_plan_build_review_spec(PlanBuildReviewParams())
    nodes = _nodes(spec)

    assert [s.id for s in spec.root.steps] == [  # type: ignore[attr-defined]
        "explore",
        "review_loop",
        "approve_pr",
        "publish",
    ]
    explore = nodes["explore"]
    assert isinstance(explore, ParallelNode) and explore.join == "all"
    assert [b.id for b in explore.branches] == ["code_analyst", "test_analyst"]
    loop = nodes["review_loop"]
    assert isinstance(loop, LoopNode)
    assert loop.until == 'results.reviewer.data.verdict == "ok"'
    assert [s.id for s in loop.body.steps] == ["implement", "synthesizer", "reviewer"]  # type: ignore[attr-defined]
    implement = nodes["implement"]
    assert isinstance(implement, OrchestratorNode) and implement.body.id == "engineer"
    assert implement.replan is not None and implement.max_workers == 2
    assert isinstance(nodes["approve_pr"], GateNode)


def test_only_the_engineers_write_and_the_publish_is_gated() -> None:
    spec = build_plan_build_review_spec(PlanBuildReviewParams())
    nodes = _nodes(spec)

    writing = {n.id for n in nodes.values() if set(node_tools(n)) & WRITE_TOOLS}
    assert writing == {"engineer"}
    publishing = [n.id for n in nodes.values() if set(node_tools(n)) & PUBLISH_TOOLS]
    assert publishing == ["publish"]
    publish = nodes["publish"]
    assert isinstance(publish, ToolNode)
    assert publish.args["from_node"] == "implement"
    assert publish.args["body_from"] == "pr-description.md"
    assert nodes["synthesizer"].writes == "pr-description.md"
    others = {
        t for i, n in nodes.items() if i not in ("engineer", "publish") for t in node_tools(n)
    }
    assert others <= READ_TOOLS


def test_the_reviewer_answers_ok_or_changes() -> None:
    assert VERDICT_SCHEMA["properties"] == {
        "verdict": {"type": "string", "enum": ["ok", "changes"]},
        "feedback": {"type": "string"},
    }


def test_every_agent_that_checks_code_reads_it_and_knows_what_it_is_given() -> None:
    spec = build_plan_build_review_spec(PlanBuildReviewParams())
    nodes = _nodes(spec)
    agents = {i: n for i, n in nodes.items() if isinstance(n, AgentNode)}
    hub = nodes["implement"].hub

    assert set(agents) == {"code_analyst", "test_analyst", "engineer", "synthesizer", "reviewer"}
    for node in [*agents.values(), hub]:
        assert {"repo.read_file", "repo.search"} <= set(node.tools), node.role
        assert node.instructions.startswith("Your input is"), node.role
        assert STARTER not in node.instructions
    assert spec.input is not None and spec.input.required and spec.input.label
    reviewer = agents["reviewer"]
    assert reviewer.output_schema == VERDICT_SCHEMA


def test_the_ac2_fixture_is_the_templates_default_spec() -> None:
    spec = build_plan_build_review_spec(PlanBuildReviewParams())
    text = json.dumps(spec.model_dump(mode="json", by_alias=True, exclude_none=True), indent=2)
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(text + "\n", encoding="utf-8", newline="\n")
    assert FIXTURE.exists(), "run with UPDATE_FIXTURES=1 to write the fixture"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(text)
