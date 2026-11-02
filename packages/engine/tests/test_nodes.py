import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from agentic_engine.nodes import (
    NODE_MANIFESTS,
    NodeManifest,
    manifest_for,
    node_kinds,
    parameters_schema,
)
from agentic_engine.spec import WorkflowSpec, schema_issues

MANIFESTS = {m.kind: m for m in NODE_MANIFESTS}


def test_every_primitive_has_one_manifest() -> None:
    kinds = [m.kind for m in NODE_MANIFESTS]
    assert len(kinds) == len(set(kinds))
    assert sorted(kinds) == sorted(node_kinds())


def test_palette_order_and_categories() -> None:
    assert [(m.kind, m.category) for m in NODE_MANIFESTS] == [
        ("agent", "step"),
        ("tool", "step"),
        ("gate", "step"),
        ("sequence", "flow"),
        ("parallel", "flow"),
        ("router", "flow"),
        ("loop", "flow"),
        ("map", "flow"),
        ("reduce", "combine"),
    ]
    assert manifest_for("router") is MANIFESTS["router"]
    assert manifest_for("nope") is None


def _dump(manifest: NodeManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json")


@pytest.mark.parametrize("manifest", NODE_MANIFESTS, ids=lambda m: m.kind)
def test_default_is_a_valid_step(manifest: NodeManifest) -> None:
    default = _dump(manifest)["default"]
    assert default["type"] == manifest.kind
    spec = {"spec_version": "0", "id": "demo", "name": "Demo", "root": default}
    assert schema_issues(spec) == []
    # A node the palette fills from the step before it is checked after the parallel it names.
    before = [_dump(MANIFESTS["parallel"])["default"]] if manifest.fill else []
    steps = [*before, default]
    in_sequence = {**spec, "root": {"type": "sequence", "id": "root", "steps": steps}}
    WorkflowSpec.model_validate(in_sequence)


def test_default_is_written_as_a_spec_writes_it() -> None:
    reduce = _dump(MANIFESTS["reduce"])
    assert reduce["default"] == {
        "type": "reduce",
        "id": "reduce",
        "from": "parallel",
        "strategy": "concat",
    }
    assert reduce["fill"] == {"from": "previous_step"}


@pytest.mark.parametrize("manifest", NODE_MANIFESTS, ids=lambda m: m.kind)
def test_parameters_leave_out_type_id_and_slots(manifest: NodeManifest) -> None:
    properties = manifest.parameters["properties"]
    hidden = {"type", "id", *(s for s in manifest.slots if "[]" not in s)}
    assert not hidden & set(properties)
    assert not hidden & set(manifest.parameters.get("required", []))
    for target in manifest.fill:
        assert target in properties


@pytest.mark.parametrize("manifest", NODE_MANIFESTS, ids=lambda m: m.kind)
def test_slots_hold_the_nodes_of_the_default(manifest: NodeManifest) -> None:
    default = _dump(manifest)["default"]
    for slot in manifest.slots:
        head, _, field = slot.partition("[].")
        values = [item[field] for item in default[head]] if field else [default[head]]
        children: list[dict[str, Any]] = []
        for v in values:
            children.extend(cast(list[dict[str, Any]], v) if isinstance(v, list) else [v])
        assert children and all("type" in c and "id" in c for c in children)


def test_agent_parameters() -> None:
    parameters = MANIFESTS["agent"].parameters
    assert set(parameters["properties"]) == {
        "role",
        "instructions",
        "provider",
        "model",
        "tools",
        "input_schema",
        "output_schema",
        "reads",
        "writes",
    }
    assert parameters["required"] == ["role", "instructions"]


def test_router_routes_keep_their_fields_but_not_their_node() -> None:
    parameters = MANIFESTS["router"].parameters
    assert set(parameters["properties"]) == {"routes", "classifier"}
    route = parameters["$defs"]["Route"]
    assert set(route["properties"]) == {"id", "when", "description"}
    assert "then" not in route.get("required", [])


def test_parameters_drop_unused_defs_and_leave_the_model_alone() -> None:
    class Child(BaseModel):
        name: str

    class Holder(BaseModel):
        type: str
        id: str
        label: str
        body: Child

    before = Holder.model_json_schema()
    schema = parameters_schema(Holder, ["body"])
    assert set(schema["properties"]) == {"label"}
    assert "$defs" not in schema
    assert Holder.model_json_schema() == before


FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "node-types.json"


def test_web_fixture_is_the_registry() -> None:
    """The web's palette tests answer `GET /node-types` with this file: regenerate it with
    `scripts/export_workflow_schema.py` when a manifest changes."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture == [m.model_dump(mode="json") for m in NODE_MANIFESTS]
