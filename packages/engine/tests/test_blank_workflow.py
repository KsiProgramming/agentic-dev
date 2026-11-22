"""A blank workflow (5.8): its id from its name, and the one starter agent it begins with."""

import json
from pathlib import Path
from typing import get_args

import pytest

from agentic_engine.nodes import (
    STARTER_STEP_ID,
    blank_spec,
    manifest_for,
    workflow_slug,
)
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import AgentNode, SequenceNode, schema_issues, validate_workflow
from agentic_runtime import Provider

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "workflow-slugs.json"
CASES: list[dict[str, str]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["slug"] for c in CASES])
def test_the_slug_is_the_one_the_start_screen_shows(case: dict[str, str]) -> None:
    slug = workflow_slug(case["name"])
    assert slug == case["slug"]
    assert len(slug) <= 63


def test_a_blank_workflow_is_one_starter_agent_that_can_run() -> None:
    spec = blank_spec("Release notes", description="Writes them.")

    assert (spec.id, spec.name, spec.description) == (
        "release-notes",
        "Release notes",
        "Writes them.",
    )
    assert isinstance(spec.root, SequenceNode)
    [step] = spec.root.steps
    agent = manifest_for("agent")
    assert agent is not None
    assert step == agent.default.model_copy(update={"id": STARTER_STEP_ID})
    data = spec.model_dump(mode="json", exclude_none=True)
    assert schema_issues(data) == []
    issues = validate_workflow(
        data, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="m"
    )
    assert issues == []


def test_the_id_and_provider_are_kept_when_given() -> None:
    spec = blank_spec("Release notes", id="notes", provider="claude")

    assert spec.id == "notes"
    assert spec.provider == "claude"
    assert isinstance(spec.root, SequenceNode)
    assert isinstance(spec.root.steps[0], AgentNode)
    assert spec.root.steps[0].provider is None  # the workflow's provider is what the agent follows


def test_copilot_is_the_workflows_provider_when_chosen() -> None:
    spec = blank_spec("Release notes", provider="copilot")

    assert spec.provider == "copilot"
    assert (
        validate_workflow(
            spec.model_dump(mode="json", exclude_none=True),
            policy=PLATFORM_POLICY,
            priced=lambda _model: True,
            default_model="claude-sonnet-5-5",
        )
        == []
    )


def test_a_blank_workflow_names_no_provider_unless_asked() -> None:
    assert blank_spec("Release notes").provider is None


def test_the_providers_are_the_agents() -> None:
    field = AgentNode.model_fields["provider"].annotation
    assert set(get_args(Provider)) == {
        arg for t in get_args(field) for arg in get_args(t) if arg is not None
    }
