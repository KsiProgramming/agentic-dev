"""A fake agent asked for structured output (6.8): with `fit_schemas`, a typed node's answer is
its input when that matches its `output_schema`, else a small value built from the schema. That
lets an orchestrator's hub plan and a typed reviewer answer on a stack with no provider. Without
it, a fake agent echoes as before (engine tests rely on a wrong-shaped echo failing a port)."""

import json

from pydantic import JsonValue

from agentic_runtime import AgentRequest, Message
from agentic_runtime.fake import FakeRuntime, fit_to_schema, schema_instance
from agentic_runtime.testing import collect_and_check

PLAN: dict[str, JsonValue] = {
    "type": "object",
    "required": ["tasks", "reason"],
    "properties": {
        "tasks": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "title", "instructions"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,62}$"},
                    "title": {"type": "string", "minLength": 1},
                    "instructions": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string", "maxLength": 300},
    },
    "additionalProperties": False,
}
VERDICT: dict[str, JsonValue] = {
    "type": "object",
    "required": ["verdict", "feedback"],
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "changes"]},
        "feedback": {"type": "string"},
    },
}


def typed(input: str, schema: dict[str, JsonValue] | None) -> AgentRequest:
    return AgentRequest(
        node_id="hub", role="Lead", instructions="Plan.", input=input, output_schema=schema
    )


async def answer(runtime: FakeRuntime, request: AgentRequest) -> str:
    events = await collect_and_check(runtime, request)
    return next(e.text for e in events if isinstance(e, Message))


def test_a_plan_has_one_task_whose_id_fits_the_pattern() -> None:
    assert schema_instance(PLAN) == {
        "tasks": [{"id": "fake", "title": "fake", "instructions": "fake"}],
        "reason": "fake",
    }


def test_enums_examples_bounds_and_patterns_are_honoured() -> None:
    assert schema_instance(VERDICT) == {"verdict": "ok", "feedback": "fake"}
    assert schema_instance({"type": "string", "examples": ["given"]}) == "given"
    assert schema_instance({"type": "string", "pattern": "^[0-9]+$"}) == "0"
    assert schema_instance({"type": "string", "minLength": 6}) == "fakexx"
    assert schema_instance({"type": "array", "items": {"type": "integer"}, "minItems": 2}) == [0, 0]
    assert schema_instance({"type": "array", "maxItems": 0}) == []
    assert schema_instance({"type": ["null", "boolean"]}) is True
    assert schema_instance({"type": "number", "minimum": 3}) == 3


def test_an_input_that_already_fits_is_kept() -> None:
    fits = json.dumps({"verdict": "changes", "feedback": "More tests."})
    assert fit_to_schema(fits, VERDICT) == fits
    assert json.loads(fit_to_schema("# A description", VERDICT)) == schema_instance(VERDICT)
    assert json.loads(fit_to_schema('{"verdict": "maybe"}', VERDICT)) == schema_instance(VERDICT)


async def test_a_typed_node_answers_a_fitted_value_when_asked_to_fit() -> None:
    runtime = FakeRuntime(fit_schemas=True)

    planned = json.loads(await answer(runtime, typed("Two analysts' notes.", PLAN)))

    assert [t["id"] for t in planned["tasks"]] == ["fake"]
    assert await answer(runtime, typed("plain", None)) == "plain"


async def test_without_fit_schemas_a_typed_node_still_echoes() -> None:
    assert (
        await answer(FakeRuntime(), typed("Two analysts' notes.", PLAN)) == "Two analysts' notes."
    )
