"""Typed ports (4.2): which schemas a port takes, and how a value is checked against one."""

from typing import Any

import pytest

from agentic_engine.ports import (
    MAX_ERROR_TEXT,
    MAX_PORT_ERRORS,
    PortError,
    PortFailure,
    check_port,
    check_value,
    parse_value,
    schema_problem,
)
from agentic_engine.spec import parse_spec, port_edges

FINDINGS: dict[str, Any] = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["severity"],
                "properties": {"severity": {"enum": ["low", "high"]}},
            },
        }
    },
}


def test_an_object_schema_is_a_port_schema() -> None:
    assert schema_problem(FINDINGS) is None
    dialect = "https://json-schema.org/draft/2020-12/schema"
    assert schema_problem({**FINDINGS, "$schema": dialect}) is None
    assert schema_problem({"type": "object", "$defs": {"a": {}}, "$ref": "#/$defs/a"}) is None


@pytest.mark.parametrize(
    ("schema", "problem"),
    [
        ({"type": "array"}, 'its root must be `"type": "object"`'),
        ({"properties": {}}, 'its root must be `"type": "object"`'),
        (
            {"type": "object", "properties": {"a": {"type": "list"}}},
            "not a valid JSON Schema at /properties/a/type",
        ),
        (
            {"type": "object", "properties": {"a": {"$ref": "https://example.com/a.json"}}},
            "`$ref` 'https://example.com/a.json' is not local",
        ),
        (
            {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"},
            "only JSON Schema 2020-12",
        ),
        ({"type": "object", "description": "x" * 17_000}, "larger than 16 KB"),
    ],
)
def test_a_schema_a_port_cannot_take_says_why(schema: dict[str, Any], problem: str) -> None:
    assert problem in (schema_problem(schema) or "")


def test_a_matching_value_has_no_errors() -> None:
    assert check_value(FINDINGS, {"findings": [{"severity": "low"}]}) == []


def test_errors_point_at_the_value_and_put_the_most_relevant_first() -> None:
    errors = check_value(FINDINGS, {"findings": [{"severity": "urgent"}]})

    assert errors == [
        PortError(pointer="/findings/0/severity", message="'urgent' is not one of ['low', 'high']")
    ]
    assert check_value(FINDINGS, {})[0] == PortError(
        pointer="", message="'findings' is a required property"
    )


def test_at_most_ten_errors_are_kept() -> None:
    errors = check_value(FINDINGS, {"findings": [{"severity": n} for n in range(30)]})

    assert len(errors) == MAX_PORT_ERRORS


def test_a_value_is_parsed_from_its_text_or_its_one_fenced_block() -> None:
    assert parse_value('{"a": 1}') == {"a": 1}
    assert parse_value('Here it is:\n```json\n{"a": 1}\n```\nDone.') == {"a": 1}
    with pytest.raises(ValueError, match="Expecting value"):
        parse_value("Two:\n```\n{}\n```\n```\n{}\n```")
    with pytest.raises(ValueError, match="Expecting value"):
        parse_value("hello")


def test_a_value_is_parsed_from_the_object_an_answer_ends_with() -> None:
    """An agent asked to end its answer with a JSON object may say a sentence first (seen on a
    real audit run, 4.6)."""
    answer = 'I reviewed the repository.\n\n{"findings": [{"message": "a {brace}"}], "n": 1}\n'
    assert parse_value(answer) == {"findings": [{"message": "a {brace}"}], "n": 1}
    assert parse_value('Done: {"a": 1}\n{"b": {"c": 2}}') == {"b": {"c": 2}}
    with pytest.raises(ValueError, match="Extra data"):
        parse_value('{"a": 1}\nThat is all.')
    with pytest.raises(ValueError, match="Expecting value"):
        parse_value("Here:\n[1, 2]")


def test_check_port_gives_the_matching_object() -> None:
    assert check_port("output", "scan", FINDINGS, '{"findings": []}') == {"findings": []}
    assert check_port("output", "scan", FINDINGS, {"findings": []}) == {"findings": []}


def test_a_value_that_is_not_json_names_the_node_and_where_it_broke() -> None:
    failure = check_port("output", "scan", FINDINGS, "hello")

    assert isinstance(failure, PortFailure)
    assert failure.error == "output of 'scan' is not JSON: Expecting value: line 1 column 1"
    assert failure.payload() == {
        "side": "output",
        "node_id": "scan",
        "from_node_id": None,
        "errors": [{"pointer": "", "message": "not JSON: Expecting value: line 1 column 1"}],
    }


def test_a_wrong_shape_on_the_input_names_both_ends_of_the_edge() -> None:
    value = '{"findings": [{"severity": "urgent"}, {}]}'

    failure = check_port("input", "report", FINDINGS, value, from_node_id="triage")

    assert isinstance(failure, PortFailure)
    assert failure.error == (
        "input of 'report' (from 'triage') does not match its input_schema at /findings/1: "
        "'severity' is a required property (and 1 more)"
    )
    assert failure.from_node_id == "triage"


def test_the_error_line_is_capped() -> None:
    key = "k" * 600
    schema: dict[str, Any] = {"type": "object", "properties": {key: {"type": "string"}}}

    failure = check_port("output", "scan", schema, {key: 1})

    assert isinstance(failure, PortFailure)
    assert len(failure.error) == MAX_ERROR_TEXT
    assert failure.error.endswith("…")


def test_edges_join_consecutive_steps_through_gates_and_nested_sequences() -> None:
    def agent(node_id: str) -> dict[str, Any]:
        return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go."}

    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "wf",
            "name": "Workflow",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    agent("a"),
                    {"type": "gate", "id": "check", "title": "Check"},
                    {"type": "sequence", "id": "inner", "steps": [agent("b"), agent("c")]},
                    {
                        "type": "map",
                        "id": "each",
                        "over": "[1]",
                        "max_concurrency": 1,
                        "body": {
                            "type": "sequence",
                            "id": "body",
                            "steps": [agent("d"), agent("e")],
                        },
                    },
                    agent("f"),
                ],
            },
        }
    )

    edges = [(p.id, c.id, path) for p, c, path in port_edges(spec.root)]

    assert edges == [
        ("a", "b", "root.steps[2].steps[0]"),
        ("b", "c", "root.steps[2].steps[1]"),
        ("d", "e", "root.steps[3].body.steps[1]"),
    ]
