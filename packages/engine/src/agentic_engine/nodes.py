"""Node manifests (5.3): what each primitive is, how the builder shows it, its parameters and the
node the palette adds. The builder's palette, cards and side panel (5.4) are drawn from them
(`GET /node-types`), so a primitive the engine knows needs no web change. Manifests are code for
now; composites (6.6) and plugins (10.1) add theirs to the same list."""

from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_serializer

from agentic_engine.spec import (
    CREATE_TOOLS,
    PLATFORM_TOOLS,
    PUBLISH_TOOLS,
    AgentNode,
    GateNode,
    LoopNode,
    MapNode,
    Node,
    ParallelNode,
    ReduceNode,
    RouterNode,
    SequenceNode,
    ToolNode,
)

type Category = Literal["step", "flow", "combine"]
"""Where the palette lists a kind: `step` does one thing, `flow` holds other nodes and decides
how they run, `combine` joins what ran before it."""

type Fill = Literal["previous_step"]
"""What the palette sets a parameter to when it adds a node: `previous_step` is the id of the
step the node is added after."""

_NODE = TypeAdapter[Node](Node)

AGENT_TOOLS: tuple[str, ...] = tuple(sorted(PLATFORM_TOOLS - PUBLISH_TOOLS - CREATE_TOOLS))
"""The tools an agent may be granted: publishing and creating a repo are irreversible, so only a
tool node may call those (`publish_not_tool_node`, `create_not_tool_node`)."""

UI_WIDGETS = frozenset({"textarea", "checkboxes"})
"""The `ui:widget`s a manifest's `ui` may name; the side panel draws each."""

UI_FIELDS = frozenset({"json"})
"""The `ui:field`s a manifest's `ui` may name: `json` edits an object as JSON text."""

UI_OPTIONS = frozenset({"advanced", "addable", "removable", "orderable"})
"""The `ui:options` a manifest's `ui` may set: `advanced` puts a field in the panel's collapsed
"Advanced" group; `addable`, `removable` and `orderable` (false) fix a list's length and order
where they are structure, like a router's routes."""

_TITLES = {"ttl_s": "Time to live (seconds)", "from": "From step"}
"""Field titles that a field name in sentence case would not make readable."""


class NodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(description="The node's `type`.")
    label: str = Field(description="Its name in the palette and on its card: `Agent`.")
    description: str = Field(description="One sentence on what it does.")
    category: Category
    icon: str = Field(description="A lucide icon name in kebab case, e.g. `bot`.")
    parameters: dict[str, Any] = Field(
        description="JSON Schema of its editable fields: the node's schema without `type`, `id` "
        "and the slots that hold nodes."
    )
    slots: list[str] = Field(
        description="The fields that hold child nodes, a node or a list of them: `steps`, "
        "`body`, `routes[].then` (each route's `then`). Empty for a leaf."
    )
    default: Node = Field(
        description="A whole node the palette adds, children included; the palette gives each "
        "node in it a fresh id."
    )
    fill: dict[str, Fill] = Field(
        default_factory=dict[str, Fill],
        description="Parameters the palette sets when it adds the node, e.g. `from` to the "
        "previous step's id.",
    )
    ui: dict[str, Any] = Field(
        default_factory=dict[str, Any],
        description="How the side panel lays out `parameters`: an rjsf `uiSchema` keyed by "
        "field, with `ui:order`, `ui:widget` (`textarea`, `checkboxes`), `ui:field` (`json`), "
        "`ui:placeholder`, `ui:readonly` and `ui:options` (`advanced`, `addable`, `removable`, "
        "`orderable`).",
    )

    @field_serializer("default")
    def _default_as_written(self, default: Node) -> dict[str, Any]:
        # As a spec writes it: `from` for a reduce's source, and no unset fields.
        return _NODE.dump_python(default, mode="json", by_alias=True, exclude_none=True)


def parameters_schema(model: type[BaseModel], slots: list[str]) -> dict[str, Any]:
    """`model`'s JSON Schema without `type`, `id` and the fields that hold nodes (`routes[].then`
    drops `then` from a route's schema), and without the `$defs` that are left unused. It is made
    ready for a form (`_for_forms`); the spec's own schema does not change."""
    schema = model.model_json_schema(mode="validation")
    defs: dict[str, Any] = schema.get("$defs", {})
    if "$ref" in schema:  # a recursive model's root is one of its `$defs`
        schema = dict(defs[schema["$ref"].removeprefix("#/$defs/")])
    # Copied before the drops below, so the model's own schema is never changed.
    defs = {k: dict(v) for k, v in defs.items()}
    _drop(schema, {"type", "id", *(s for s in slots if "[]" not in s)})
    for slot in (s for s in slots if "[]" in s):
        head, _, field = slot.partition("[].")
        items = schema["properties"][head]["items"]
        ref = items.get("$ref", "")
        _drop(defs[ref.removeprefix("#/$defs/")] if ref else items, {field})
    used = _refs({k: v for k, v in schema.items() if k != "$defs"}, defs)
    if used:
        schema["$defs"] = {k: v for k, v in defs.items() if k in used}
    else:
        schema.pop("$defs", None)
    return cast(dict[str, Any], _for_forms(schema))


_NULL = {"type": "null"}


def _for_forms(value: object, name: str | None = None) -> object:
    """`value` (a schema, or anything in one) as a form draws it: an optional field's
    `anyOf: [X, null]` becomes `X` (a field not required may be unset), a `const` becomes a
    one-value `enum`, and each property's title is in sentence case."""
    if isinstance(value, list):
        return [_for_forms(item) for item in cast(list[object], value)]
    if not isinstance(value, dict):
        return value
    schema = dict(cast(dict[str, object], value))
    options = cast(list[object], schema.get("anyOf", []))
    if len(options) == 2 and _NULL in options:
        kept = cast(dict[str, object], next(o for o in options if o != _NULL))
        del schema["anyOf"]
        if "default" in schema and schema["default"] is None:
            del schema["default"]
        schema = {**kept, **schema}
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
    if name is not None:
        schema["title"] = _TITLES.get(name) or name.replace("_", " ").capitalize()
    out: dict[str, object] = {}
    for key, item in schema.items():
        if key == "properties" and isinstance(item, dict):
            props = cast(dict[str, object], item)
            out[key] = {k: _for_forms(v, k) for k, v in props.items()}
        elif key == "$defs" and isinstance(item, dict):
            out[key] = {k: _for_forms(v) for k, v in cast(dict[str, object], item).items()}
        elif key in ("items", "additionalProperties", "anyOf", "oneOf", "allOf"):
            out[key] = _for_forms(item)
        else:
            out[key] = item
    return out


def _with_choices(parameters: dict[str, Any], choices: dict[str, tuple[str, ...]]) -> None:
    """Give each named field (a string, or a list of strings) of `parameters` its choices as an
    `enum`. Only the form gets them: the spec still takes any name, and validation explains a
    wrong one (`unknown_tool`)."""
    for field, values in choices.items():
        prop = parameters["properties"][field]
        if prop.get("type") == "array":
            prop["items"] = {**prop["items"], "enum": list(values)}
            prop["uniqueItems"] = True
        else:
            prop["enum"] = list(values)


def _drop(schema: dict[str, Any], fields: set[str]) -> None:
    schema["properties"] = {k: v for k, v in schema["properties"].items() if k not in fields}
    if "required" in schema:
        schema["required"] = [k for k in schema["required"] if k not in fields]


def _refs(value: object, defs: dict[str, Any], found: set[str] | None = None) -> set[str]:
    """The `$defs` names `value` reaches, through other `$defs` too."""
    found = set[str]() if found is None else found
    if isinstance(value, dict):
        for key, item in cast(dict[str, object], value).items():
            if key == "$ref" and isinstance(item, str):
                name = item.removeprefix("#/$defs/")
                if name not in found:
                    found.add(name)
                    _refs(defs.get(name), defs, found)
            else:
                _refs(item, defs, found)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            _refs(item, defs, found)
    return found


def _agent(id: str = "agent") -> dict[str, Any]:
    return {
        "type": "agent",
        "id": id,
        "role": "Agent",
        "instructions": "Describe what this agent does.",
    }


def _manifest(
    model: type[BaseModel],
    *,
    label: str,
    description: str,
    category: Category,
    icon: str,
    default: dict[str, Any],
    slots: list[str] | None = None,
    fill: dict[str, Fill] | None = None,
    choices: dict[str, tuple[str, ...]] | None = None,
    ui: dict[str, Any] | None = None,
) -> NodeManifest:
    slots = slots or []
    parameters = parameters_schema(model, slots)
    _with_choices(parameters, choices or {})
    return NodeManifest(
        kind=default["type"],
        label=label,
        description=description,
        category=category,
        icon=icon,
        parameters=parameters,
        slots=slots,
        default=_NODE.validate_python(default),
        fill=fill or {},
        ui=ui or {},
    )


_TEXTAREA = {"ui:widget": "textarea"}
_ADVANCED = {"ui:options": {"advanced": True}}
_JSON_ADVANCED = {"ui:field": "json", **_ADVANCED}
_PORTS_AND_ARTIFACTS = {
    "input_schema": _JSON_ADVANCED,
    "output_schema": _JSON_ADVANCED,
    "reads": _ADVANCED,
    "writes": _ADVANCED,
}
_MODEL = {"ui:placeholder": "The workspace's default"}


NODE_MANIFESTS: tuple[NodeManifest, ...] = (
    _manifest(
        AgentNode,
        label="Agent",
        description="One agent turn: a role and instructions run on a model.",
        category="step",
        icon="bot",
        default=_agent(),
        choices={"tools": AGENT_TOOLS},
        ui={
            "ui:order": ["role", "instructions", "provider", "model", "tools", "*"],
            "instructions": _TEXTAREA,
            "model": _MODEL,
            "tools": {"ui:widget": "checkboxes"},
            **_PORTS_AND_ARTIFACTS,
        },
    ),
    _manifest(
        ToolNode,
        label="Tool",
        description="Calls one platform tool with fixed arguments; no model is involved.",
        category="step",
        icon="wrench",
        default={"type": "tool", "id": "tool", "tool": "repo.list_files"},
        choices={"tool": tuple(sorted(PLATFORM_TOOLS))},
        ui={"args": {"ui:field": "json"}, **_PORTS_AND_ARTIFACTS},
    ),
    _manifest(
        GateNode,
        label="Gate",
        description="Pauses the run until someone approves or rejects.",
        category="step",
        icon="shield-check",
        default={"type": "gate", "id": "gate", "title": "Approve"},
        ui={"prompt": _TEXTAREA, "ttl_s": _ADVANCED},
    ),
    _manifest(
        SequenceNode,
        label="Sequence",
        description="Runs its steps in order.",
        category="flow",
        icon="list-ordered",
        slots=["steps"],
        default={"type": "sequence", "id": "sequence", "steps": [_agent()]},
    ),
    _manifest(
        ParallelNode,
        label="Parallel",
        description="Runs its branches at the same time and joins them.",
        category="flow",
        icon="split",
        slots=["branches"],
        default={
            "type": "parallel",
            "id": "parallel",
            "branches": [_agent("agent"), _agent("agent_b")],
            "join": "all",
        },
        ui={"quorum": {"ui:placeholder": "With the quorum join only"}},
    ),
    _manifest(
        RouterNode,
        label="Router",
        description="Runs one of its routes, chosen by a rule or a classifier agent.",
        category="flow",
        icon="signpost",
        slots=["routes[].then", "default"],
        default={
            "type": "router",
            "id": "router",
            "routes": [{"id": "match", "when": "true", "then": _agent("agent")}],
            "default": _agent("agent_b"),
        },
        ui={
            "routes": {
                "ui:options": {"addable": False, "removable": False, "orderable": False},
                "items": {
                    "id": {"ui:readonly": True},
                    "when": {"ui:placeholder": 'A CEL condition, e.g. last.contains("bug")'},
                    "description": _TEXTAREA,
                },
            },
            "classifier": {"instructions": _TEXTAREA, "model": _MODEL},
        },
    ),
    _manifest(
        LoopNode,
        label="Loop",
        description="Runs its body again until a condition holds, a set number of times at most.",
        category="flow",
        icon="repeat",
        slots=["body"],
        default={
            "type": "loop",
            "id": "loop",
            "body": _agent(),
            "until": "iteration >= 3",
            "max_iterations": 3,
        },
        ui={"until": {"ui:placeholder": "A CEL condition, e.g. iteration >= 3"}},
    ),
    _manifest(
        MapNode,
        label="Map",
        description="Runs its body once per item of a list.",
        category="flow",
        icon="layers",
        slots=["body"],
        default={
            "type": "map",
            "id": "map",
            "over": "[last]",
            "body": _agent(),
            "max_concurrency": 4,
        },
        ui={"over": {"ui:placeholder": "A CEL list, e.g. results.modules.data.modules"}},
    ),
    _manifest(
        ReduceNode,
        label="Reduce",
        description="Combines the outputs of the map or parallel before it.",
        category="combine",
        icon="merge",
        default={"type": "reduce", "id": "reduce", "from": "parallel", "strategy": "concat"},
        fill={"from": "previous_step"},
        ui={
            "ui:order": ["from", "strategy", "*"],
            "agent": {"instructions": _TEXTAREA, "model": _MODEL},
            "writes": _ADVANCED,
        },
    ),
)
"""Every primitive's manifest, in palette order."""


def manifest_for(kind: str) -> NodeManifest | None:
    return next((m for m in NODE_MANIFESTS if m.kind == kind), None)


def node_kinds() -> list[str]:
    """The `type` of each member of the `Node` union, so a test can ask each for a manifest."""
    union = get_args(Node)[0]
    return [get_args(m.model_fields["type"].annotation)[0] for m in get_args(union)]
