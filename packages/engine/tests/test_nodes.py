import json
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from agentic_engine.nodes import (
    AGENT_TOOLS,
    NODE_MANIFESTS,
    UI_FIELDS,
    UI_OPTIONS,
    UI_WIDGETS,
    NodeManifest,
    composite_manifest,
    manifest_for,
    node_kinds,
    parameters_schema,
)
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import PLATFORM_TOOLS, WorkflowSpec, schema_issues, validate_workflow

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
        ("orchestrator", "flow"),
        ("subflow", "flow"),
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


def _schemas(value: object) -> list[dict[str, Any]]:
    """Every object in `value`, depth first, leaving out `examples` (values, not schemas)."""
    if isinstance(value, list):
        return [s for item in cast(list[object], value) for s in _schemas(item)]
    if not isinstance(value, dict):
        return []
    node = cast(dict[str, Any], value)
    inner = (item for key, item in node.items() if key != "examples")
    return [node, *(s for item in inner for s in _schemas(item))]


@pytest.mark.parametrize("manifest", NODE_MANIFESTS, ids=lambda m: m.kind)
def test_parameters_are_ready_for_a_form(manifest: NodeManifest) -> None:
    for schema in _schemas(manifest.parameters):
        assert {"type": "null"} not in schema.get("anyOf", []), schema
        assert "const" not in schema, schema
        for name, prop in cast(dict[str, Any], schema.get("properties", {})).items():
            title: str = prop["title"]
            assert name == "ttl_s" or (title[0].isupper() and title[1:] == title[1:].lower())


def test_optional_fields_keep_their_type_and_drop_the_null_default() -> None:
    properties = MANIFESTS["agent"].parameters["properties"]
    assert properties["provider"] == {
        "type": "string",
        "enum": ["claude"],
        "title": "Provider",
        "description": "Unset means the workspace default.",
    }
    assert properties["model"] == {"type": "string", "minLength": 1, "title": "Model"}
    assert properties["input_schema"]["title"] == "Input schema"
    assert MANIFESTS["gate"].parameters["properties"]["ttl_s"]["title"] == "Time to live (seconds)"


def test_agents_choose_tools_they_may_be_granted() -> None:
    tools = MANIFESTS["agent"].parameters["properties"]["tools"]
    assert tools["items"]["enum"] == list(AGENT_TOOLS)
    assert tools["uniqueItems"] is True
    assert "github.openPR" not in AGENT_TOOLS and "github.createRepo" not in AGENT_TOOLS
    agent = {"type": "agent", "id": "a", "role": "a", "instructions": "Do a.", "tools": AGENT_TOOLS}
    spec = {"spec_version": "0", "id": "demo", "name": "Demo", "root": agent}
    issues = validate_workflow(
        spec, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="m"
    )
    assert issues == []


def test_tool_nodes_choose_any_platform_tool_but_the_spec_takes_any_name() -> None:
    tool = MANIFESTS["tool"].parameters["properties"]["tool"]
    assert tool["enum"] == sorted(PLATFORM_TOOLS)
    node = {"type": "tool", "id": "t", "tool": "no.such_tool"}
    spec = {"spec_version": "0", "id": "demo", "name": "Demo", "root": node}
    assert schema_issues(spec) == []
    issues = validate_workflow(
        spec, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="m"
    )
    assert [i.code for i in issues] == ["unknown_tool"]


def _ui_fields(ui: dict[str, Any], schema: dict[str, Any], defs: dict[str, Any]) -> None:
    """Check each key of `ui` against `schema`, recursing into objects and list items."""
    if "$ref" in schema:
        schema = {**defs[schema["$ref"].removeprefix("#/$defs/")], **schema}
    properties = cast(dict[str, Any], schema.get("properties", {}))
    for key, value in ui.items():
        if key == "ui:order":
            assert set(value) - {"*"} <= set(properties), value
        elif key == "ui:widget":
            assert value in UI_WIDGETS
        elif key == "ui:field":
            assert value in UI_FIELDS
        elif key == "ui:options":
            assert set(value) <= UI_OPTIONS
        elif key in ("ui:placeholder", "ui:readonly"):
            pass
        elif key == "items":
            _ui_fields(value, schema["items"], defs)
        else:
            assert key in properties, f"{key!r} is not a parameter"
            _ui_fields(value, properties[key], defs)


@pytest.mark.parametrize("manifest", NODE_MANIFESTS, ids=lambda m: m.kind)
def test_ui_names_parameters_and_known_widgets(manifest: NodeManifest) -> None:
    _ui_fields(manifest.ui, manifest.parameters, manifest.parameters.get("$defs", {}))


def test_router_routes_cannot_be_added_removed_or_renamed() -> None:
    routes = MANIFESTS["router"].ui["routes"]
    assert routes["ui:options"] == {"addable": False, "removable": False, "orderable": False}
    assert routes["items"]["id"] == {"ui:readonly": True}


FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "node-types.json"


def test_web_fixture_is_the_registry() -> None:
    """The web's palette tests answer `GET /node-types` with this file: regenerate it with
    `scripts/export_workflow_schema.py` when a manifest changes."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture == [m.model_dump(mode="json") for m in NODE_MANIFESTS]


def test_a_composite_entry_adds_a_subflow_pinned_to_its_published_version() -> None:
    """A workspace's composite (6.6) is listed as a `subflow` under its own name: the palette
    adds a call to its latest published version, edited with the subflow's side panel."""
    entry = composite_manifest("security-review", 3, "Security review", "Checks for leaks.")
    subflow = manifest_for("subflow")
    assert subflow is not None

    assert (entry.kind, entry.label, entry.category) == ("subflow", "Security review", "workspace")
    assert entry.description == "Checks for leaks."
    assert entry.composite is not None
    assert (entry.composite.workflow_id, entry.composite.version) == ("security-review", 3)
    dumped = entry.model_dump(mode="json")
    assert dumped["default"] == {
        "type": "subflow",
        "id": "subflow",
        "workflow": {"id": "security-review", "version": 3},
    }
    assert (entry.parameters, entry.ui, entry.slots) == (subflow.parameters, subflow.ui, [])
    # The primitives' lookup never returns a composite's entry.
    assert manifest_for("subflow") is subflow
    assert composite_manifest("w", 1, "W").description == "Runs the composite W, version 1."
