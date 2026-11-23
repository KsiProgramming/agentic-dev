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
    validate_workflow,
)

GATE: dict[str, Any] = {"type": "gate", "id": "approve", "title": "Go?"}
WRITER: dict[str, Any] = {
    "type": "agent",
    "id": "writer",
    "role": "Writer",
    "instructions": "Write NOTES.md.",
    "tools": ["repo.write_file", "repo.commit"],
}
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
    assert OUTWARD_WRITE_TOOLS == {
        "github.openPR",
        "github.createRepo",
        "jira.comment",
        "jira.transition",
    }
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
