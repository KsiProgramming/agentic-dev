"""`validate_workflow`: every reason a spec cannot run, each with its code, path and node."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agentic_engine.policy import PLATFORM_POLICY, Policy
from agentic_engine.spec import ValidationIssue, validate_workflow
from agentic_engine.templates import TEMPLATES

FIXTURES = Path(__file__).parent / "fixtures" / "specs"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def validate(
    raw: object, policy: Policy = PLATFORM_POLICY, priced: frozenset[str] = frozenset({"default"})
) -> list[ValidationIssue]:
    return validate_workflow(
        raw, policy=policy, priced=priced.__contains__, default_model="default"
    )


def where(issues: list[ValidationIssue]) -> list[tuple[str, str, str | None]]:
    return [(issue.code, issue.path, issue.node_id) for issue in issues]


def workflow(root: dict[str, Any]) -> dict[str, Any]:
    return {"spec_version": "0", "id": "wf", "name": "Workflow", "root": root}


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **fields}


@pytest.mark.parametrize("path", sorted((FIXTURES / "valid").glob("*.json")), ids=lambda p: p.stem)
def test_valid_specs_have_no_issues(path: Path) -> None:
    assert validate(json.loads(path.read_text(encoding="utf-8"))) == []


def test_every_template_has_no_issues() -> None:
    for template in TEMPLATES:
        spec = template.build_spec({})
        assert validate(spec.model_dump(mode="json", by_alias=True)) == [], template.id


INVALID: dict[str, tuple[str, str, str | None]] = {
    "artifact-bad-name": ("schema", "root.writes", "scan"),
    "artifact-branch-conflict": ("artifact_conflict", "root.branches[1]", "quality"),
    "artifact-read-before-write": ("artifact_unknown", "root.steps[0].reads[0]", "report"),
    "artifact-write-in-map": ("artifact_conflict", "root.body", "scan"),
    "bad-node-id": ("schema", "root.id", "Writer/One"),
    "create-repo-after-repo-use": ("create_not_first", "root.steps[2]", "create_repo"),
    "create-repo-by-agent": ("create_not_tool_node", "root.steps[1]", "creator"),
    "create-repo-nested": ("create_not_first", "root.steps[1].steps[0]", "create_repo"),
    "create-repo-twice": ("create_not_first", "root.steps[2]", "create_again"),
    "create-repo-without-gate": ("create_without_gate", "root.steps[0]", "create_repo"),
    "duplicate-node-id": ("duplicate_node_id", "root.steps[1].steps[0]", "writer"),
    "empty-sequence": ("schema", "root.steps", "main"),
    "extra-key": ("schema", "root.temprature", "writer"),
    "gate-missing-title": ("schema", "root.steps[1].title", "gate"),
    "loop-bad-cel": ("invalid_expression", "root", "revise"),
    "loop-too-many-iterations": ("schema", "root.max_iterations", "revise"),
    "loop-with-gate": ("not_allowed_in_loop", "root.body.steps[1]", "check"),
    "loop-with-writer": ("not_allowed_in_loop", "root.body", "writer"),
    "map-bad-cel": ("invalid_expression", "root", "each"),
    "map-too-concurrent": ("schema", "root.max_concurrency", "each"),
    "map-with-gate": ("not_allowed_in_map", "root.body.steps[1]", "check"),
    "map-with-writer": ("not_allowed_in_map", "root.body", "writer"),
    "missing-instructions": ("schema", "root.instructions", "writer"),
    "nested-loop": ("not_allowed_in_loop", "root.body", "inner"),
    "nested-map": ("not_allowed_in_map", "root.body", "inner"),
    "parallel-in-loop": ("not_allowed_in_loop", "root.body", "review"),
    "parallel-in-map": ("not_allowed_in_map", "root.body", "review"),
    "parallel-one-branch": ("schema", "root.branches", "review"),
    "parallel-quorum-too-high": ("schema", "root", "review"),
    "parallel-quorum-without-join": ("schema", "root", "review"),
    "parallel-too-many-branches": ("schema", "root.branches", "review"),
    "parallel-with-gate": ("not_allowed_in_parallel", "root.branches[1].steps[1]", "check"),
    "parallel-with-loop": ("not_allowed_in_parallel", "root.branches[1]", "revise"),
    "parallel-with-writer": ("not_allowed_in_parallel", "root.branches[1]", "writer"),
    "open-pr-by-agent": ("publish_not_tool_node", "root.steps[0]", "writer"),
    "open-pr-gate-before-writer": ("publish_without_gate", "root.steps[2]", "publish"),
    "open-pr-unknown-from-node": ("reference", "root.steps[2]", "publish"),
    "open-pr-without-gate": ("publish_without_gate", "root.steps[1]", "publish"),
    "port-invalid-schema": ("invalid_schema", "root.output_schema", "triage"),
    "port-mismatch-required": ("port_mismatch", "root.steps[2]", "report"),
    "port-mismatch-type": ("port_mismatch", "root.steps[1]", "report"),
    "port-not-object": ("invalid_schema", "root.output_schema", "triage"),
    "port-remote-ref": ("invalid_schema", "root.input_schema", "triage"),
    "reduce-agent-missing": ("schema", "root.steps[1]", "join"),
    "reduce-before-map": ("reference", "root.steps[0]", "join"),
    "reduce-from-non-map": ("reference", "root.steps[1]", "join"),
    "reduce-unknown-from": ("reference", "root.steps[1]", "join"),
    "tool-node-missing-tool": ("schema", "root.tool", "list"),
    "unknown-node-type": ("schema", "root", "route"),
    "unknown-provider": ("schema", "root.provider", "writer"),
    "wrong-spec-version": ("schema", "spec_version", None),
}


def test_every_invalid_fixture_is_covered() -> None:
    assert sorted(INVALID) == sorted(p.stem for p in (FIXTURES / "invalid").glob("*.json"))


@pytest.mark.parametrize("name", sorted(INVALID))
def test_an_invalid_spec_gets_one_issue_on_the_node_to_fix(name: str) -> None:
    [issue] = validate(load(f"invalid/{name}.json"))

    assert (issue.code, issue.path, issue.node_id) == INVALID[name]
    if issue.node_id is not None:
        assert repr(issue.node_id) in issue.message


def test_schema_issues_name_the_node_and_the_field_without_union_tags() -> None:
    [issue] = validate(load("invalid/gate-missing-title.json"))

    assert issue.message == "gate 'gate' at root.steps[1]: title: Field required"
    assert "'gate', 'title'" not in issue.message


def test_a_schema_failure_reports_only_schema_issues() -> None:
    raw = workflow(
        {
            "type": "sequence",
            "id": "main",
            "steps": [
                agent("a", tools=["repo.nope"]),
                {"type": "gate", "id": "a"},  # no title, and a duplicate id
            ],
        }
    )

    assert where(validate(raw)) == [("schema", "root.steps[1].title", "a")]


def test_a_document_that_is_not_an_object_is_a_schema_issue() -> None:
    [issue] = validate([1, 2])

    assert (issue.code, issue.path, issue.node_id) == ("schema", "", None)


def test_every_problem_is_reported_in_run_order() -> None:
    raw = workflow(
        {
            "type": "sequence",
            "id": "main",
            "steps": [
                {"type": "reduce", "id": "join", "from": "later", "strategy": "concat"},
                agent("helper", tools=["repo.read_file", "web.fetch"]),
                {
                    "type": "loop",
                    "id": "review",
                    "until": "true",
                    "max_iterations": 2,
                    "body": {"type": "gate", "id": "ok", "title": "OK?"},
                },
                agent("helper"),
            ],
        }
    )

    assert where(validate(raw)) == [
        ("reference", "root.steps[0]", "join"),
        ("unknown_tool", "root.steps[1]", "helper"),
        ("not_allowed_in_loop", "root.steps[2].body", "ok"),
        ("duplicate_node_id", "root.steps[3]", "helper"),
    ]


def test_an_unknown_tool_lists_the_platform_tools() -> None:
    [issue] = validate(workflow({"type": "tool", "id": "t", "tool": "repo.delete"}))

    assert issue.code == "unknown_tool"
    assert "unknown tool 'repo.delete'" in issue.message
    assert "repo.read_file" in issue.message


def test_a_reduce_from_itself_is_a_reference_issue() -> None:
    raw = workflow({"type": "reduce", "id": "join", "from": "join", "strategy": "concat"})

    assert where(validate(raw)) == [("reference", "root", "join")]


def test_limits_lowered_by_the_workspace_are_policy_issues() -> None:
    lowered = PLATFORM_POLICY.model_copy(update={"loop_iterations": 2, "agents_alive": 3})
    raw = workflow(
        {
            "type": "sequence",
            "id": "main",
            "steps": [
                {
                    "type": "loop",
                    "id": "revise",
                    "until": "true",
                    "max_iterations": 3,
                    "body": agent("a"),
                },
                {
                    "type": "map",
                    "id": "each",
                    "over": "[1]",
                    "max_concurrency": 4,
                    "body": agent("b"),
                },
            ],
        }
    )

    issues = validate(raw, lowered)

    assert [(i.code, i.path, i.node_id, i.limit, i.value, i.observed) for i in issues] == [
        ("policy_limit", "root.steps[0]", "revise", "loop_iterations", 2, 3),
        ("policy_limit", "root.steps[1]", "each", "agents_alive", 3, 4),
    ]
    assert validate(raw) == []


def test_a_parallel_with_more_branches_than_agents_alive_is_a_policy_issue() -> None:
    lowered = PLATFORM_POLICY.model_copy(update={"agents_alive": 2})
    raw = workflow(
        {
            "type": "parallel",
            "id": "review",
            "join": "all",
            "branches": [agent("a"), agent("b"), agent("c")],
        }
    )

    issues = validate(raw, lowered)

    assert [(i.code, i.path, i.node_id, i.limit, i.value, i.observed) for i in issues] == [
        ("policy_limit", "root", "review", "agents_alive", 2, 3)
    ]
    assert validate(raw) == []


def test_a_budget_needs_a_price_for_every_agent_model() -> None:
    budgeted = PLATFORM_POLICY.model_copy(update={"budget_usd": Decimal("1")})
    raw = workflow(
        {
            "type": "sequence",
            "id": "main",
            "steps": [agent("priced"), agent("unpriced", model="no-such-model")],
        }
    )

    [issue] = validate(raw, budgeted)

    assert (issue.code, issue.node_id, issue.limit) == (
        "budget_unpriced_model",
        "unpriced",
        "budget_usd",
    )
    assert "model 'no-such-model' has no price" in issue.message
    assert validate(raw) == []
