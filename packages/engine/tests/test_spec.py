import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_engine.spec import WorkflowSpec, parse_spec

FIXTURES = Path(__file__).parent / "fixtures" / "specs"
VALID = sorted((FIXTURES / "valid").glob("*.json"))


@dataclass(frozen=True)
class Rejection:
    """Where and why an invalid fixture must fail, so it fails for the intended reason."""

    loc: tuple[str | int, ...]
    type: str
    msg: str = ""


INVALID: dict[str, Rejection] = {
    "unknown-node-type": Rejection(("root",), "union_tag_invalid"),
    "missing-instructions": Rejection(("root", "agent", "instructions"), "missing"),
    "extra-key": Rejection(("root", "agent", "temprature"), "extra_forbidden"),
    "duplicate-node-id": Rejection((), "value_error", "'writer' at root.steps[1].steps[0]"),
    "empty-sequence": Rejection(("root", "sequence", "steps"), "too_short"),
    "bad-node-id": Rejection(("root", "agent", "id"), "string_pattern_mismatch"),
    "wrong-spec-version": Rejection(("spec_version",), "literal_error"),
    "unknown-provider": Rejection(("root", "agent", "provider"), "literal_error"),
    "tool-node-missing-tool": Rejection(("root", "tool", "tool"), "missing"),
    "gate-missing-title": Rejection(("root", "sequence", "steps", 1, "gate", "title"), "missing"),
    "open-pr-without-gate": Rejection(
        (), "value_error", "'publish': github.openPR must come after a gate that follows 'writer'"
    ),
    "open-pr-gate-before-writer": Rejection(
        (), "value_error", "must come after a gate that follows 'writer'"
    ),
    "open-pr-unknown-from-node": Rejection(
        (), "value_error", "`from_node` 'editor' is not a node that runs before it"
    ),
    "open-pr-by-agent": Rejection(
        (), "value_error", "'writer': github.openPR can only be called by a tool node"
    ),
    "loop-bad-cel": Rejection(
        (), "value_error", "loop 'revise' at root: invalid until: syntax error at column 15"
    ),
    "loop-too-many-iterations": Rejection(("root", "loop", "max_iterations"), "less_than_equal"),
    "loop-with-gate": Rejection(
        (), "value_error", "gate 'check' at root.body.steps[1] cannot be inside a loop"
    ),
    "loop-with-writer": Rejection(
        (), "value_error", "writer 'writer' at root.body cannot be inside a loop"
    ),
    "nested-loop": Rejection(
        (), "value_error", "loop 'outer' at root: loop 'inner' at root.body cannot be inside"
    ),
}


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_invalid_fixture_has_an_expectation() -> None:
    names = {p.stem for p in (FIXTURES / "invalid").glob("*.json")}
    assert names == set(INVALID)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_spec(path: Path) -> None:
    spec = parse_spec(load(path))

    assert WorkflowSpec.model_validate(spec.model_dump(mode="json")) == spec


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalid_spec(name: str) -> None:
    expected = INVALID[name]
    with pytest.raises(ValidationError) as exc:
        parse_spec(load(FIXTURES / "invalid" / f"{name}.json"))

    errors = exc.value.errors()
    assert any(
        e["loc"] == expected.loc and e["type"] == expected.type and expected.msg in e["msg"]
        for e in errors
    ), errors


def test_exported_schema_has_discriminated_node_union() -> None:
    schema_path = Path(__file__).resolve().parents[3] / "schemas" / "workflow-spec.v0.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    root = schema["properties"]["root"]
    assert root["discriminator"]["propertyName"] == "type"
    assert set(root["discriminator"]["mapping"]) == {"agent", "tool", "gate", "sequence", "loop"}
    assert {ref["$ref"] for ref in root["oneOf"]} == {
        "#/$defs/AgentNode",
        "#/$defs/ToolNode",
        "#/$defs/GateNode",
        "#/$defs/SequenceNode",
        "#/$defs/LoopNode",
    }
    loop = schema["$defs"]["LoopNode"]["properties"]["max_iterations"]
    assert (loop["minimum"], loop["maximum"]) == (1, 5)
