"""`validate_workflow`: every reason a workflow document cannot run in a workspace, in one pass.

The API's `POST /workflows/{id}/validate` answers with it, and later the canvas and the Flow
Architect use it too, so they never disagree with what `POST /runs` accepts.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import cast

from pydantic import TypeAdapter, ValidationError
from pydantic_core import ErrorDetails

from agentic_engine.policy import Policy
from agentic_engine.spec.models import (
    PLATFORM_TOOLS,
    Node,
    ValidationIssue,
    WorkflowSpec,
    budget_issues,
    in_run_order,
    policy_issues,
    structure_issues,
    tool_issues,
)

_NODE: TypeAdapter[Node] = TypeAdapter(Node)


def validate_workflow(
    raw: object,
    *,
    policy: Policy,
    priced: Callable[[str], bool],
    default_model: str,
    known_tools: Collection[str] = PLATFORM_TOOLS,
) -> list[ValidationIssue]:
    """Why the decoded JSON document `raw` cannot run under `policy`; empty if it can. Never
    raises for a bad document.

    A document that does not match the schema gets only `schema` issues: the other checks need
    its nodes. Otherwise the issues are its structure (`structure_issues`), unknown tools, the
    policy's limits and, with a budget, agents on models `priced` does not know (an agent with no
    `model` runs on `default_model`), in run order."""
    try:
        root = WorkflowSpec.model_validate(raw).root
    except ValidationError as e:
        errors = e.errors()
        if not all(error["type"] == "value_error" and not error["loc"] for error in errors):
            return [_schema_issue(raw, error) for error in errors]
        # Only the document's own validators failed, so its nodes are well formed.
        root = _NODE.validate_python(cast(Mapping[str, object], raw)["root"])
    issues = structure_issues(root) + tool_issues(root, known_tools)
    issues += policy_issues(root, policy)
    issues += budget_issues(root, policy, priced, default_model)
    return in_run_order(root, issues)


def _schema_issue(raw: object, error: ErrorDetails) -> ValidationIssue:
    """`error` on the spec's own path, on the innermost node it is in. Pydantic puts a node's
    type tag after its place (`root`, `sequence`, `steps`, 1, `agent`, `role`); the spec does
    not have it."""
    path: list[int | str] = []
    node: Mapping[str, object] | None = None
    node_depth = 0
    value: object = raw
    tagged = False  # whether `part` may be the type tag of the node just entered
    for part in error["loc"]:
        if tagged and part == cast(Mapping[str, object], value)["type"]:
            tagged = False
            continue
        path.append(part)
        value = _child(value, part)
        tagged = _is_node(value)
        if tagged:
            node, node_depth = cast(Mapping[str, object], value), len(path)
    message = error["msg"].removeprefix("Value error, ")
    if field := _render(path[node_depth:]):
        message = f"{field}: {message}"
    node_id = node.get("id") if node is not None else None
    node_id = node_id if isinstance(node_id, str) else None
    if node is not None:
        name = f"{node['type']} {node_id!r}" if node_id else str(node["type"])
        message = f"{name} at {_render(path[:node_depth])}: {message}"
    return ValidationIssue(code="schema", path=_render(path), node_id=node_id, message=message)


def _render(path: Sequence[int | str]) -> str:
    """`["root", "steps", 1, "role"]` -> `root.steps[1].role`."""
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else f".{part}" if text else part
    return text


def _is_node(value: object) -> bool:
    return isinstance(value, Mapping) and isinstance(
        cast(Mapping[str, object], value).get("type"), str
    )


def _child(value: object, part: int | str) -> object:
    if isinstance(part, int) and isinstance(value, Sequence) and not isinstance(value, str):
        items = cast(Sequence[object], value)
        return items[part] if 0 <= part < len(items) else None
    if isinstance(part, str) and isinstance(value, Mapping):
        return cast(Mapping[str, object], value).get(part)
    return None
