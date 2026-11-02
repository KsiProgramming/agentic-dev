import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

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
    "artifact-bad-name": Rejection(("root", "agent", "writes"), "string_pattern_mismatch"),
    "artifact-branch-conflict": Rejection(
        (), "value_error", "writes 'findings.json', which branch 'security' of parallel 'review'"
    ),
    "artifact-read-before-write": Rejection(
        (), "value_error", "reads 'findings.json', which no node writes before it"
    ),
    "artifact-write-in-map": Rejection(
        (), "value_error", "writes 'findings.json' inside map 'each'"
    ),
    "unknown-node-type": Rejection(("root",), "union_tag_invalid"),
    "router-mixed-modes": Rejection(
        ("root", "router"), "value_error", "route 'bug' has `when`, but a classifier chooses"
    ),
    "router-bad-cel": Rejection((), "value_error", "route 'bug': invalid when: syntax error"),
    "router-route-is-parallel": Rejection(
        (), "value_error", "route 'both' is parallel 'review'; a route is one agent, tool or"
    ),
    "router-artifact-one-route": Rejection(
        (), "value_error", "reads 'report.md', which no node writes before it"
    ),
    "router-writer-in-map": Rejection(
        (), "value_error", "writer 'writer' at root.body.routes[0].then cannot be inside a map"
    ),
    "parallel-reduce-writes": Rejection(
        (), "value_error", "writing reduce 'inner_merge' at root.branches[1].steps[1] cannot be"
    ),
    "reduce-from-inside-branch": Rejection(
        (), "value_error", "`from` 'inner' runs inside root.steps[0].branches[1], which the reduce"
    ),
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
    "create-repo-by-agent": Rejection(
        (), "value_error", "'creator': github.createRepo can only be called by a tool node"
    ),
    "create-repo-without-gate": Rejection(
        (), "value_error", "'create_repo': github.createRepo must come after a gate"
    ),
    "create-repo-after-repo-use": Rejection(
        (), "value_error", "must come before 'list', which uses the repo"
    ),
    "create-repo-nested": Rejection((), "value_error", "must be a step of the root sequence"),
    "create-repo-twice": Rejection((), "value_error", "a workflow creates at most one repo"),
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
    "map-bad-cel": Rejection(
        (), "value_error", "map 'each' at root: invalid over: syntax error at column 26"
    ),
    "map-too-concurrent": Rejection(("root", "map", "max_concurrency"), "less_than_equal"),
    "map-with-gate": Rejection(
        (), "value_error", "gate 'check' at root.body.steps[1] cannot be inside a map"
    ),
    "map-with-writer": Rejection(
        (), "value_error", "writer 'writer' at root.body cannot be inside a map"
    ),
    "nested-map": Rejection(
        (), "value_error", "map 'outer' at root: map 'inner' at root.body cannot be inside"
    ),
    "reduce-unknown-from": Rejection(
        (),
        "value_error",
        "reduce 'join' at root.steps[1]: `from` 'eaches' is not a map or parallel",
    ),
    "reduce-from-non-map": Rejection(
        (),
        "value_error",
        "reduce 'join' at root.steps[1]: `from` 'writer' is not a map or parallel",
    ),
    "reduce-before-map": Rejection(
        (), "value_error", "reduce 'join' at root.steps[0]: `from` 'each' is not a map or parallel"
    ),
    "reduce-agent-missing": Rejection(
        ("root", "sequence", "steps", 1, "reduce"), "value_error", "the agent strategy needs"
    ),
    "reduce-min-votes-on-dedupe": Rejection(
        ("root", "sequence", "steps", 1, "reduce"), "value_error", "`min_votes` is only used"
    ),
    "reduce-vote-unreachable": Rejection(
        (), "value_error", "`min_votes` 3 is more than the 2 branches the quorum join"
    ),
    "reduce-merge-not-findings": Rejection(
        (), "value_error", "reduce 'merge' merges its output as a findings report"
    ),
    "parallel-one-branch": Rejection(("root", "parallel", "branches"), "too_short"),
    "parallel-too-many-branches": Rejection(("root", "parallel", "branches"), "too_long"),
    "parallel-quorum-too-high": Rejection(
        ("root", "parallel"), "value_error", "`quorum` 4 must be from 1 to the 3 branches"
    ),
    "parallel-quorum-without-join": Rejection(
        ("root", "parallel"), "value_error", "`quorum` is only used by the quorum join"
    ),
    "parallel-with-gate": Rejection(
        (), "value_error", "gate 'check' at root.branches[1].steps[1] cannot be inside a parallel"
    ),
    "parallel-with-writer": Rejection(
        (), "value_error", "writer 'writer' at root.branches[1] cannot be inside a parallel"
    ),
    "parallel-with-loop": Rejection(
        (), "value_error", "loop 'revise' at root.branches[1] cannot be inside a parallel"
    ),
    "parallel-in-map": Rejection(
        (), "value_error", "map 'each' at root: parallel 'review' at root.body cannot be inside"
    ),
    "parallel-in-loop": Rejection(
        (), "value_error", "loop 'revise' at root: parallel 'review' at root.body cannot be inside"
    ),
    "port-invalid-schema": Rejection(
        (), "value_error", "output_schema: it is not a valid JSON Schema at /properties/findings"
    ),
    "port-not-object": Rejection((), "value_error", 'its root must be `"type": "object"`'),
    "port-remote-ref": Rejection(
        (), "value_error", "`$ref` 'https://example.com/findings.json' is not local"
    ),
    "port-mismatch-required": Rejection(
        (), "value_error", "requires 'issues', which the output_schema of 'triage' does not"
    ),
    "port-mismatch-type": Rejection(
        (), "value_error", "wants 'findings' as string, but the output_schema of 'triage' gives"
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
    assert set(root["discriminator"]["mapping"]) == {
        "agent",
        "tool",
        "gate",
        "sequence",
        "loop",
        "map",
        "reduce",
        "parallel",
        "router",
    }
    assert {ref["$ref"] for ref in root["oneOf"]} == {
        "#/$defs/AgentNode",
        "#/$defs/ToolNode",
        "#/$defs/GateNode",
        "#/$defs/SequenceNode",
        "#/$defs/LoopNode",
        "#/$defs/MapNode",
        "#/$defs/ReduceNode",
        "#/$defs/ParallelNode",
        "#/$defs/RouterNode",
    }
    loop = schema["$defs"]["LoopNode"]["properties"]["max_iterations"]
    assert (loop["minimum"], loop["maximum"]) == (1, 5)
    concurrency = schema["$defs"]["MapNode"]["properties"]["max_concurrency"]
    assert (concurrency["minimum"], concurrency["maximum"]) == (1, 8)
    reduce = schema["$defs"]["ReduceNode"]
    assert "from" in reduce["required"]
    assert reduce["properties"]["strategy"]["enum"] == ["concat", "agent", "dedupe", "vote"]
    parallel = schema["$defs"]["ParallelNode"]["properties"]
    assert (parallel["branches"]["minItems"], parallel["branches"]["maxItems"]) == (2, 8)
    assert parallel["join"]["enum"] == ["all", "any", "quorum", "settled"]


def test_a_workflow_budget_is_optional_and_in_range() -> None:
    spec = cast(dict[str, object], load(FIXTURES / "valid" / "single-agent.json"))

    assert parse_spec(spec).budget_usd is None
    assert parse_spec({**spec, "budget_usd": 2.5}).budget_usd == 2.5
    for bad in (0, -1, 0.001, 2_000_000):
        with pytest.raises(ValidationError):
            WorkflowSpec.model_validate({**spec, "budget_usd": bad})
