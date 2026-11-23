"""The plan of an outward write (13.8): the set of tools that have one, and the arguments only the
engine passes."""

from typing import Any

import pytest

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    CREATE_TOOLS,
    JIRA_WRITE_TOOLS,
    OUTWARD_WRITE_TOOLS,
    PLATFORM_TOOLS,
    PUBLISH_TOOLS,
    WorkflowSpec,
    planned_writes,
    validate_workflow,
)
from agentic_engine.templates import (
    AuditParams,
    DocsParams,
    NewRepo,
    SddParams,
    build_audit_spec,
    build_docs_spec,
    build_sdd_spec,
    wrap_with_create_repo,
)

GATE: dict[str, Any] = {"type": "gate", "id": "approve", "title": "Go?"}
WRITER: dict[str, Any] = {
    "type": "agent",
    "id": "writer",
    "role": "Writer",
    "instructions": "Write NOTES.md.",
    "tools": ["repo.write_file", "repo.commit"],
}


def CALL(tool: str, args: dict[str, Any], id: str) -> dict[str, Any]:
    return {"type": "tool", "id": id, "tool": tool, "args": args}


def doc(root: dict[str, Any]) -> dict[str, Any]:
    return {"spec_version": "0", "id": "w", "name": "W", "root": root}


CALLS: dict[str, dict[str, Any]] = {
    "jira.comment": {"issue": "API-1", "body": "Done."},
    "jira.transition": {"issue": "API-1", "to": "Done"},
    "github.openPR": {"from_node": "writer", "title": "Add notes"},
    "github.createRepo": {"name": "docs-demo"},
}


def issues(tool: str, **extra: Any) -> list[tuple[str, str | None]]:
    call: dict[str, Any] = {
        "type": "tool",
        "id": "write",
        "tool": tool,
        "args": CALLS[tool] | extra,
    }
    steps = [WRITER, GATE, call] if tool == "github.openPR" else [GATE, call]
    raw = {
        "spec_version": "0",
        "id": "w",
        "name": "W",
        "root": {"type": "sequence", "id": "main", "steps": steps},
    }
    found = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
    )
    return [(i.code, i.path) for i in found]


def test_the_outward_writes_are_the_tools_that_publish_create_or_write_to_jira() -> None:
    assert OUTWARD_WRITE_TOOLS == PUBLISH_TOOLS | CREATE_TOOLS | JIRA_WRITE_TOOLS
    assert {
        "github.openPR",
        "github.createRepo",
        "jira.comment",
        "jira.transition",
    } == OUTWARD_WRITE_TOOLS
    assert OUTWARD_WRITE_TOOLS <= PLATFORM_TOOLS


@pytest.mark.parametrize("tool", sorted(OUTWARD_WRITE_TOOLS))
def test_the_calls_in_these_tests_are_valid_as_written(tool: str) -> None:
    assert issues(tool) == []


@pytest.mark.parametrize("tool", sorted(OUTWARD_WRITE_TOOLS))
@pytest.mark.parametrize(("name", "value"), [("plan", True), ("expect", {"tip": "abc"})])
def test_a_spec_cannot_set_what_only_the_engine_passes(tool: str, name: str, value: Any) -> None:
    found = issues(tool, **{name: value})

    assert found == [
        ("reference", f"root.steps[{1 if tool != 'github.openPR' else 2}].args.{name}")
    ]


# --- which gate plans which write ---------------------------------------------------------------


def writes_of(spec: WorkflowSpec) -> dict[str, list[str]]:
    return planned_writes(spec.root)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (SddParams(), {"approve_pr": ["publish", "jira_update"]}),
        (SddParams(move_to="Done"), {"approve_pr": ["publish", "jira_update", "move"]}),
        # With checks, the checks gate passes by itself or pauses, and shows the plans too.
        (
            SddParams(checks=True, move_to="Done"),
            {
                "checks": ["publish", "jira_update", "move"],
                "approve_pr": ["publish", "jira_update", "move"],
            },
        ),
        (
            SddParams(checks=True, review=True, move_to="Done"),
            {
                "checks": ["publish", "jira_update", "move"],
                "approve_pr": ["publish", "jira_update", "move"],
            },
        ),
    ],
)
def test_the_sdd_gates_plan_the_pull_request_and_the_jira_writes(
    params: SddParams, expected: dict[str, list[str]]
) -> None:
    found = writes_of(build_sdd_spec(params))

    # `post_questions` plans only the comment that asks, `approve_spec` nothing.
    assert found.pop("post_questions") == ["ask_jira"]
    assert "approve_spec" not in found
    assert found == expected


def test_a_gate_does_not_plan_what_the_next_decision_covers() -> None:
    twice = {
        "type": "sequence",
        "id": "main",
        "steps": [
            GATE,
            CALL("jira.comment", {"issue": "API-1", "body": "Hi."}, "first"),
            {**GATE, "id": "again"},
            CALL("jira.transition", {"issue": "API-1", "to": "Done"}, "second"),
        ],
    }

    assert planned_writes(WorkflowSpec.model_validate(doc(twice)).root) == {
        "approve": ["first"],
        "again": ["second"],
    }


def test_a_write_on_another_route_is_not_planned_by_a_gate_of_a_route() -> None:
    router = {
        "type": "router",
        "id": "pick",
        "routes": [
            {
                "id": "a",
                "when": "true",
                "then": {
                    "type": "sequence",
                    "id": "route_a",
                    "steps": [GATE, CALL("jira.comment", {"issue": "API-1", "body": "A."}, "ca")],
                },
            },
            {
                "id": "b",
                "when": "false",
                "then": {
                    "type": "sequence",
                    "id": "route_b",
                    "steps": [
                        {**GATE, "id": "gb"},
                        CALL("jira.comment", {"issue": "API-1", "body": "B."}, "cb"),
                    ],
                },
            },
        ],
    }

    found = planned_writes(WorkflowSpec.model_validate(doc(router)).root)

    assert found == {"approve": ["ca"], "gb": ["cb"]}


def test_templates_with_one_gate_plan_the_write_after_it() -> None:
    assert writes_of(build_docs_spec(DocsParams())) == {"approve": ["publish"]}
    assert writes_of(build_audit_spec(AuditParams(fix=True))) == {"approve_pr": ["publish"]}
    assert writes_of(build_audit_spec(AuditParams())) == {}


def test_the_new_repo_gate_plans_creating_the_repo() -> None:
    wrapped = wrap_with_create_repo(
        build_docs_spec(DocsParams()), NewRepo(name="docs-demo"), "acme"
    )

    assert writes_of(wrapped) == {"approve_repo": ["create_repo"], "approve": ["publish"]}


def test_a_wait_plans_nothing_and_a_gate_with_no_write_after_it_has_no_plans() -> None:
    wait = {"type": "wait_for", "id": "answers", "title": "Answered?", "after_from": "ask"}
    ask = CALL("jira.comment", {"issue": "API-1", "body": "Questions?"}, "ask")
    spec = WorkflowSpec.model_validate(
        doc({"type": "sequence", "id": "main", "steps": [GATE, ask, wait]})
    )

    assert planned_writes(spec.root) == {"approve": ["ask"]}
    assert planned_writes(WorkflowSpec.model_validate(doc(GATE)).root) == {}
