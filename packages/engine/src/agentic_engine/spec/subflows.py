"""Resolving subflows (6.5): the workflows a spec calls, attached to it for one run.

A `subflow` node names a stored workflow by id and version. Before a run (or a check of one), every
subflow is resolved through a `Resolve` callable, the called workflow's root attached to the node
(`SubflowNode.call`), and the subflows inside it resolved in turn: the expanded tree is what
validation checks and the engine runs. A workflow may not call itself, directly or through
others (`subflow_cycle`), an unknown workflow or version is `subflow_unknown`, and a version of a
composite that was never published (a draft, 6.6) is `subflow_unpublished`. An issue found
inside a called workflow is reported on the outermost subflow that calls it, as the parent's
author can only change the call.

The resolver reads stored workflow versions (`agentic_store.subflows`) or, for a run, the copies
taken when it was created (`runs.subflows`), keyed by `subflow_key`.
"""

from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field
from typing import cast

from pydantic import JsonValue, TypeAdapter, ValidationError

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.ports import schema_problem
from agentic_engine.spec.models import (
    PLATFORM_TOOLS,
    IssueCode,
    LoopNode,
    MapNode,
    Node,
    OrchestratorNode,
    ParallelNode,
    ReduceNode,
    RouterNode,
    SequenceNode,
    SubflowNode,
    ToolNode,
    ValidationIssue,
    WorkflowSpec,
    in_run_order,
    iter_nodes,
    structure_issues,
    tool_issues,
)

type Resolve = Callable[[str, int], JsonValue | None]
"""The spec document (decoded JSON) of version `version` of the workspace's workflow `id`, or
`None` when the workspace has no such workflow or version."""

MAX_CALL_NESTING = PLATFORM_POLICY.max_depth + 1
"""How deep calls are resolved at most. A call is a level of `max_depth`, which a workspace may
lower but never raise, so a deeper call is a `policy_limit` issue whatever is resolved below it;
resolving no further keeps a chain of calls from growing the tree without bound."""

_NODE: TypeAdapter[Node] = TypeAdapter(Node)


def subflow_key(workflow_id: str, version: int) -> str:
    """How a called version is known in a run's copies (`runs.subflows`): `docs@3`."""
    return f"{workflow_id}@{version}"


def no_subflows(workflow_id: str, version: int) -> JsonValue | None:
    """A `Resolve` that knows no workflow: every subflow is `subflow_unknown`."""
    return None


def resolve_from(documents: Mapping[str, JsonValue]) -> Resolve:
    """A `Resolve` over copies keyed by `subflow_key`."""
    return lambda workflow_id, version: documents.get(subflow_key(workflow_id, version))


def subflow_refs(raw: object) -> Iterator[tuple[str, int]]:
    """The `(workflow id, version)` every subflow in the decoded document `raw` calls, as written
    (malformed ones left out); used to read them before a check, which is synchronous."""
    match raw:
        case {"type": "subflow", "workflow": {"id": str() as workflow_id, "version": int() as v}}:
            yield workflow_id, v
        case dict():
            for value in cast(dict[str, object], raw).values():
                yield from subflow_refs(value)
        case list():
            for value in cast(list[object], raw):
                yield from subflow_refs(value)
        case _:
            pass


@dataclass
class ExpandedWorkflow:
    """A spec with its subflows resolved (`spec`), the documents they called by `subflow_key`
    (`called`, what a run keeps), and why the calls cannot run (`issues`: unknown or cyclic
    calls, then everything wrong inside a called workflow, on its subflow)."""

    spec: WorkflowSpec
    called: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    issues: list[ValidationIssue] = field(default_factory=list[ValidationIssue])


def expand_workflow(
    spec: WorkflowSpec,
    resolve: Resolve,
    known_tools: Collection[str] = PLATFORM_TOOLS,
    drafts: Collection[str] = (),
) -> ExpandedWorkflow:
    """`spec` with every subflow resolved through `resolve`, the documents called, and why it
    cannot run: unknown and cyclic calls, then the structure and tool issues of the expanded tree
    (`structure_issues`, `tool_issues` against `known_tools`), each inside a called workflow moved
    onto its subflow (`on_subflows`). A call to a version in `drafts` (`subflow_key`s of
    composites' unpublished versions, 6.6) is `subflow_unpublished`. A spec with no subflow is
    returned as it is, with no issues: parsing it checked its structure already. Policy limits
    are the caller's to check, on the expanded spec."""
    root, called, issues = expand_root(spec.root, resolve, spec.id, drafts)
    if root is spec.root:
        return ExpandedWorkflow(spec)
    issues += structure_issues(root) + tool_issues(root, known_tools)
    expanded = spec.model_copy(update={"root": root})
    return ExpandedWorkflow(expanded, called, on_subflows(root, in_run_order(root, issues)))


def expand_root(
    root: Node,
    resolve: Resolve,
    workflow_id: str | None = None,
    drafts: Collection[str] = (),
) -> tuple[Node, dict[str, JsonValue], list[ValidationIssue]]:
    """As `expand_workflow`, for the root of workflow `workflow_id` (which it may not call): the
    expanded root (`root` itself when it has no subflow), the documents called and the issues."""
    called: dict[str, JsonValue] = {}
    issues: list[ValidationIssue] = []
    used = {node.id for _, node in iter_nodes(root)}

    def expand(node: Node, path: str, calling: tuple[str, ...]) -> Node:
        match node:
            case SubflowNode():
                return call(node, path, calling)
            case SequenceNode():
                steps = [expand(s, f"{path}.steps[{i}]", calling) for i, s in enumerate(node.steps)]
                return node.model_copy(update={"steps": steps})
            case LoopNode() | MapNode() | OrchestratorNode():
                body = expand(node.body, f"{path}.body", calling)
                return node.model_copy(update={"body": body})
            case ParallelNode():
                branches = [
                    expand(b, f"{path}.branches[{i}]", calling) for i, b in enumerate(node.branches)
                ]
                return node.model_copy(update={"branches": branches})
            case RouterNode():
                routes = [
                    r.model_copy(
                        update={"then": expand(r.then, f"{path}.routes[{i}].then", calling)}
                    )
                    for i, r in enumerate(node.routes)
                ]
                default = node.default
                if default is not None:
                    default = expand(default, f"{path}.default", calling)
                return node.model_copy(update={"routes": routes, "default": default})
            case _:
                return node

    def call(node: SubflowNode, path: str, calling: tuple[str, ...]) -> Node:
        ref = node.workflow
        name = f"workflow {ref.id!r} version {ref.version}"
        if ref.id in calling:
            chain = " → ".join(repr(w) for w in (*calling, ref.id))
            why = f"calls {ref.id!r} again ({chain}); a workflow may not call itself, directly "
            issues.append(_issue("subflow_cycle", node, path, why + "or through others"))
            return node
        if len(calling) > MAX_CALL_NESTING:
            return node  # `policy_issues` reports the depth.
        raw = resolve(ref.id, ref.version)
        if raw is None:
            issues.append(_issue("subflow_unknown", node, path, f"the workspace has no {name}"))
            return node
        parsed = _parse(raw)
        if parsed is None:
            issues.append(_issue("subflow_unknown", node, path, f"{name} is not a workflow spec"))
            return node
        if subflow_key(ref.id, ref.version) in drafts:
            why = (
                f"{name} is a draft; {ref.id!r} is a composite, so call one of its published "
                "versions, or publish this one"
            )
            issues.append(_issue("subflow_unpublished", node, path, why))
        called[subflow_key(ref.id, ref.version)] = raw
        ids = _run_ids(parsed.root, node.id, used)
        inner = expand(_renamed(parsed.root, ids), f"{path}.call", (*calling, ref.id))
        return node.resolved(inner, parsed.name, ids, parsed.input_schema, parsed.output_schema)

    if not any(isinstance(node, SubflowNode) for _, node in iter_nodes(root)):
        return root, called, issues
    calling = (workflow_id,) if workflow_id is not None else ()
    return expand(root, "root", calling), called, issues


def _run_ids(root: Node, subflow_id: str, used: set[str]) -> dict[str, str]:
    """The id each node under `root`, a called workflow's root, runs under: its own, or
    `<subflow>-<id>` (cut to fit a `NodeId`, then numbered) when a node of the run already has it.
    Adds them to `used`. A workflow written alone cannot know the ids of those that call it, and
    every blank workflow starts with the same ones."""
    ids: dict[str, str] = {}
    for _, node in iter_nodes(root):
        if node.id in ids:
            continue  # A duplicate in the called workflow stays one, and is reported.
        run_id = node.id if node.id not in used else _fresh(f"{subflow_id}-{node.id}", used)
        ids[node.id] = run_id
        used.add(run_id)
    return ids


def _fresh(base: str, used: set[str]) -> str:
    """`base` as a `NodeId` no node of the run has: at most 63 characters, numbered if taken."""
    candidate, n = base[:63], 2
    while candidate in used:
        suffix = f"-{n}"
        candidate, n = base[: 63 - len(suffix)] + suffix, n + 1
    return candidate


def _renamed(node: Node, ids: Mapping[str, str]) -> Node:
    """`node` with every node id under it, and the references to them (a reduce's `from`, a
    publishing tool's `from_node`), replaced through `ids`."""
    update: dict[str, object] = {"id": ids.get(node.id, node.id)}
    match node:
        case SequenceNode():
            update["steps"] = [_renamed(step, ids) for step in node.steps]
        case LoopNode() | MapNode() | OrchestratorNode():
            update["body"] = _renamed(node.body, ids)
        case ParallelNode():
            update["branches"] = [_renamed(branch, ids) for branch in node.branches]
        case RouterNode():
            update["routes"] = [
                r.model_copy(update={"then": _renamed(r.then, ids)}) for r in node.routes
            ]
            if node.default is not None:
                update["default"] = _renamed(node.default, ids)
        case ReduceNode():
            update["from_"] = ids.get(node.from_, node.from_)
        case ToolNode() if isinstance(source := node.args.get("from_node"), str):
            update["args"] = {**node.args, "from_node": ids.get(source, source)}
        case _:
            pass
    return node.model_copy(update=update)


def expression_views(root: Node) -> dict[str, dict[str, str]]:
    """For each node under the expanded `root` that runs inside a called workflow, how that
    workflow's expressions name the run's nodes: its own node ids to the ids they run under
    (`SubflowNode.ids`). An expression of the caller's own nodes sees every result."""
    calls = [
        (path, node)
        for path, node in iter_nodes(root)
        if isinstance(node, SubflowNode) and node.call is not None
    ]
    views: dict[str, dict[str, str]] = {}
    for path, node in iter_nodes(root):
        inside = [(at, call) for at, call in calls if path.startswith(f"{at}.call")]
        if inside:
            views[node.id] = max(inside, key=lambda found: len(found[0]))[1].ids
    return views


def call_documents(root: Node) -> dict[str, JsonValue]:
    """Each resolved subflow under the expanded `root`, by its id: the workflow it calls (`id`,
    `version`, `name`), that workflow's root as it runs (`root`: its node ids as they run, a
    subflow in it a leaf with an entry of its own), and the ids that run under another name
    (`renamed`: run id to the id in the called workflow). What a client draws a run's calls
    from."""
    found: dict[str, JsonValue] = {}
    for _, node in iter_nodes(root):
        if not isinstance(node, SubflowNode) or node.call is None:
            continue
        renamed: dict[str, JsonValue] = {new: old for old, new in node.ids.items() if new != old}
        workflow: dict[str, JsonValue] = {
            "id": node.workflow.id,
            "version": node.workflow.version,
            "name": node.called_name or node.workflow.id,
        }
        found[node.id] = {
            "workflow": workflow,
            "root": _NODE.dump_python(node.call, mode="json", by_alias=True, exclude_none=True),
            "renamed": renamed,
        }
    return found


@dataclass(frozen=True)
class _Called:
    """What a called workflow document gives its subflow: its root, name and port schemas (a
    schema a port cannot take is left out; the called workflow's own check reports it)."""

    root: Node
    name: str
    input_schema: dict[str, JsonValue] | None
    output_schema: dict[str, JsonValue] | None


def _port(schema: object) -> dict[str, JsonValue] | None:
    if not isinstance(schema, dict):
        return None
    typed = cast(dict[str, JsonValue], schema)
    return typed if schema_problem(typed) is None else None


def _parse(raw: JsonValue) -> _Called | None:
    """The root, name and port schemas of the workflow document `raw`, or `None` when it is not
    one. A stored version matches the schema but may not run: its root is still returned, and
    what is wrong with it is found on the expanded tree."""
    try:
        spec = WorkflowSpec.model_validate(raw)
    except ValidationError as e:
        if not all(err["type"] == "value_error" and not err["loc"] for err in e.errors()):
            return None
        document = cast(Mapping[str, object], raw)
        return _Called(
            _NODE.validate_python(document["root"]),
            str(document.get("name") or ""),
            _port(document.get("input_schema")),
            _port(document.get("output_schema")),
        )
    return _Called(spec.root, spec.name, _port(spec.input_schema), _port(spec.output_schema))


def on_subflows(root: Node, issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """`issues` of the expanded tree under `root` with each one inside a called workflow moved onto
    the outermost subflow calling it: its path and node, and a message that names the call. The
    called workflow's own paths in the message read from its root."""
    calls = {
        path: node
        for path, node in iter_nodes(root)
        if isinstance(node, SubflowNode) and node.call is not None and ".call" not in path
    }
    if not calls:
        return issues
    moved: list[ValidationIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        at = issue.path.partition(".call")[0] if ".call" in issue.path else None
        subflow = calls.get(at) if at is not None else None
        if at is None or subflow is None:
            moved.append(issue)
            continue
        ref = subflow.workflow
        inner = issue.message.replace(f"{at}.call", "root")
        message = (
            f"subflow {subflow.id!r} at {at}: in workflow {ref.id!r} version {ref.version}, {inner}"
        )
        if (key := (issue.code, at, message)) in seen:
            continue
        seen.add(key)
        moved.append(
            issue.model_copy(update={"path": at, "node_id": subflow.id, "message": message})
        )
    return moved


def _issue(code: IssueCode, node: SubflowNode, path: str, why: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        path=f"{path}.workflow",
        node_id=node.id,
        message=f"subflow {node.id!r} at {path}: {why}",
    )
