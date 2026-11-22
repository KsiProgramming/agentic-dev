"""`validate_workflow`: every reason a workflow document cannot run in a workspace, in one pass.

The API's `POST /workflows/{id}/validate` answers with it, and later the canvas and the Flow
Architect use it too, so they never disagree with what `POST /runs` accepts.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import cast, get_args

from pydantic import JsonValue, TypeAdapter, ValidationError
from pydantic_core import ErrorDetails

from agentic_engine.policy import Policy
from agentic_engine.ports import schema_problem
from agentic_engine.spec.models import (
    JIRA_WRITE_TOOLS,
    PLATFORM_TOOLS,
    Node,
    OnReview,
    ToolNode,
    ValidationIssue,
    WorkflowInput,
    WorkflowSpec,
    budget_issues,
    in_run_order,
    input_artifacts,
    iter_nodes,
    on_review_issues,
    policy_issues,
    structure_issues,
    tool_issues,
)
from agentic_engine.spec.providers import provider_gaps, resolve_root
from agentic_engine.spec.subflows import Resolve, expand_root, no_subflows, on_subflows
from agentic_runtime.request import Provider

_NODE: TypeAdapter[Node] = TypeAdapter(Node)


def validate_workflow(
    raw: object,
    *,
    policy: Policy,
    priced: Callable[[str], bool],
    default_model: str,
    known_tools: Collection[str] = PLATFORM_TOOLS,
    resolve: Resolve = no_subflows,
    drafts: Collection[str] = (),
    workspace_default: Provider | None = None,
    has_copilot_connection: bool | None = None,
) -> list[ValidationIssue]:
    """Why the decoded JSON document `raw` cannot run under `policy`; empty if it can. Never
    raises for a bad document.

    A document that does not match the schema gets only `schema` issues: the other checks need
    its nodes. Otherwise the issues are its structure (`structure_issues`), unknown tools, the
    policy's limits and, with a budget, agents on models `priced` does not know (an agent with no
    `model` runs on `default_model`), in run order.

    Its subflows (6.5) are resolved through `resolve`, which knows none by default, and the
    checks run on the expanded tree: a call that is unknown or cyclic is an issue on its
    subflow, and so is anything wrong inside the workflow it calls (`on_subflows`); a call to a
    version in `drafts` (a composite's unpublished version, 6.6) is `subflow_unpublished`. The
    document's own `input_schema` and `output_schema` must be port schemas (`invalid_schema`).

    With `has_copilot_connection` (8.3), a node that resolves to Copilot, under the workflow's
    `provider` and the workspace's `workspace_default`, is a `copilot_connection_required` issue
    when it is false; left `None`, the connection is not checked."""
    root = _parse_root(raw)
    if isinstance(root, list):
        return root
    document = cast(Mapping[str, object], raw)
    workflow_id = document.get("id")
    root, _, issues = expand_root(
        root, resolve, workflow_id if isinstance(workflow_id, str) else None, drafts
    )
    issues = document_port_issues(document) + issues + issue_from_issues(document, root)
    issues += document_on_review_issues(document, root)
    issues += structure_issues(root, document_input_artifacts(document))
    issues += tool_issues(root, known_tools)
    issues += policy_issues(root, policy)
    declared = document.get("provider")
    workflow_provider: Provider | None = (
        declared if declared in get_args(Provider) else None  # pyright: ignore[reportAssignmentType]
    )
    resolved = resolve_root(root, workflow_provider, workspace_default=workspace_default)
    issues += budget_issues(
        root,
        policy,
        priced,
        default_model,
        {node_id: (n.provider, n.model) for node_id, n in resolved.nodes.items()},
    )
    if has_copilot_connection is not None:
        issues += provider_gaps(resolved, has_copilot_connection=has_copilot_connection)
    return on_subflows(root, in_run_order(root, issues))


def document_port_issues(document: Mapping[str, object]) -> list[ValidationIssue]:
    """`invalid_schema` for the workflow's own `input_schema` or `output_schema` (6.6) when a port
    cannot take it, on no node."""
    issues: list[ValidationIssue] = []
    for side in ("input", "output"):
        schema = document.get(f"{side}_schema")
        if not isinstance(schema, dict):
            continue
        if (problem := schema_problem(cast(dict[str, JsonValue], schema))) is not None:
            issues.append(
                ValidationIssue(
                    code="invalid_schema",
                    path=f"{side}_schema",
                    message=f"the workflow's {side}_schema: {problem}",
                )
            )
    return issues


def document_input_artifacts(document: Mapping[str, object]) -> tuple[str, ...]:
    """The run artifacts the document's `input` gives a run before its first step (7.7); none
    when it has no valid `input`."""
    try:
        return input_artifacts(WorkflowInput.model_validate(document.get("input")))
    except ValidationError:
        return ()


def document_on_review_issues(document: Mapping[str, object], root: Node) -> list[ValidationIssue]:
    """`on_review_issues` for the document's `on_review` (7.6), checked on the expanded tree."""
    raw = document.get("on_review")
    if raw is None:
        return []
    return on_review_issues(root, OnReview.model_validate(raw))


def issue_from_issues(document: Mapping[str, object], root: Node) -> list[ValidationIssue]:
    """`reference` on each Jira write that takes its issue from the run's request
    (`issue_from: "request"`, 7.2) when the workflow does not declare a required `input`: a run
    could start without the issue key it needs."""
    declared = document.get("input")
    required = isinstance(declared, Mapping) and (
        cast(Mapping[str, object], declared).get("required") is True
    )
    if required:
        return []
    return [
        ValidationIssue(
            code="reference",
            path=f"{path}.args.issue_from",
            node_id=node.id,
            message=f'node {node.id!r}: `issue_from: "request"` needs the workflow to declare a '
            "required `input`, the issue key a run is started with",
        )
        for path, node in iter_nodes(root)
        if isinstance(node, ToolNode)
        and node.tool in JIRA_WRITE_TOOLS
        and node.args.get("issue_from") is not None
    ]


def schema_issues(raw: object) -> list[ValidationIssue]:
    """The `schema` issues of the decoded JSON document `raw`: why it is not a workflow spec at
    all. Empty when it is one, even if it could not run (`validate_workflow` says why)."""
    root = _parse_root(raw)
    return root if isinstance(root, list) else []


def _parse_root(raw: object) -> Node | list[ValidationIssue]:
    """The root node of `raw`, or its `schema` issues when it does not match the schema."""
    try:
        return WorkflowSpec.model_validate(raw).root
    except ValidationError as e:
        errors = e.errors()
        if not all(error["type"] == "value_error" and not error["loc"] for error in errors):
            return [_schema_issue(raw, error) for error in errors]
        # Only the document's own validators failed, so its nodes are well formed.
        return _NODE.validate_python(cast(Mapping[str, object], raw)["root"])


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
