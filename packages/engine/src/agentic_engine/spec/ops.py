"""Graph operations (5.1): the one way the canvas, the side panel and the Flow Architect change a
stored workflow spec.

A spec is a tree, and the ops keep it one: nodes are addressed by id, and an edge `from → to` is
sequence order (`to` is the step right after `from`). A batch may leave nodes detached while it
runs (a node added with no place, a step taken out by `disconnect`), but not at its end.
`apply_ops` applies a batch to a copy, all or nothing.
"""

import copy
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agentic_engine.spec.models import DEFAULT_ROUTE, Node, NodeId
from agentic_engine.spec.validate import schema_issues

MAX_OPS = 200
"""Ops one batch may hold."""


class _Op(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_mode_override="validation",
        validate_by_name=True,
        serialize_by_alias=True,
    )


class After(_Op):
    """Right after a step of a sequence."""

    after: NodeId = Field(description="The step the node follows.")


class Into(_Op):
    """Into a container: a sequence's step or a parallel's branch at `index`; a loop's, map's or
    orchestrator's body, which must be empty; a router route's `then`, or its `default`, which must
    be empty."""

    parent: NodeId = Field(description="The container.")
    index: int | None = Field(
        default=None, ge=0, description="Sequence and parallel only: the position (default last)."
    )
    route: NodeId | None = Field(
        default=None,
        description="Router only, and required there: the route's id, or `default`.",
    )


class AddNode(_Op):
    """Add a node, with any nodes under it, all with new ids. Without `at` it is detached, and
    must be placed (`connect`) or removed later in the same batch."""

    op: Literal["addNode"]
    node: Node
    at: After | Into | None = Field(default=None, description="Where it goes; unset: detached.")


class RemoveNode(_Op):
    """Remove a node and everything under it. Its sequence's neighbours join up. A loop's or
    map's body, or a route's `then`, must be given another node in the same batch."""

    op: Literal["removeNode"]
    node_id: NodeId


class Connect(_Op):
    """Place `to` (detached, or moved from where it is, with everything under it) right after
    `from`. When `from` is not a step of a sequence, `sequence_id` names a new sequence that
    takes `from`'s place and runs `from`, then `to`."""

    op: Literal["connect"]
    from_: NodeId = Field(alias="from")
    to: NodeId
    sequence_id: NodeId | None = Field(
        default=None,
        description="The id of the sequence to wrap `from` in, when it is not a sequence's step.",
    )


class Disconnect(_Op):
    """Detach `to`, the step right after `from`, with everything under it; the step after `to`
    now follows `from`. `to` must be placed again or removed in the same batch."""

    op: Literal["disconnect"]
    from_: NodeId = Field(alias="from")
    to: NodeId


class SetParam(_Op):
    """Set one parameter of a node, or of the document without `node_id` (`name`,
    `description`, `budget_usd`, `input`). `null` unsets it. Ids, types and the slots that hold
    nodes change through the other ops."""

    op: Literal["setParam"]
    node_id: NodeId | None = Field(default=None, description="Unset: the document.")
    path: str = Field(
        description="The parameter, by its JSON field names, e.g. `instructions`, "
        "`classifier.instructions`, `routes[1].when`.",
        examples=["instructions", "routes[1].when"],
    )
    value: JsonValue


WRAP_KINDS = ("sequence", "parallel", "loop", "map")
"""The containers `wrap` may put nodes in."""


class Wrap(_Op):
    """Put nodes in a new container, in their place (6.6): one node anywhere, or consecutive steps
    of one sequence. A `sequence` runs them in order, a `parallel` runs each as a branch (two or
    more), a `loop` or `map` runs them as its body (in a new sequence `sequence_id` when there are
    several). `with` is the container without the nodes: its `type`, a new `id` and its other
    parameters (a loop's `until` and `max_iterations`, a map's `over`)."""

    op: Literal["wrap"]
    node_ids: list[NodeId] = Field(min_length=1, max_length=MAX_OPS)
    with_: dict[str, JsonValue] = Field(
        alias="with",
        description="The new container without its nodes: `type` (sequence, parallel, loop or "
        "map), `id` and its other parameters.",
    )
    sequence_id: NodeId | None = Field(
        default=None,
        description="Loop and map only: the id of the sequence that holds the nodes, when there "
        "are several.",
    )


class ExtractedWorkflow(_Op):
    """The workflow `extract` makes."""

    id: NodeId = Field(description="Its id, new in the workspace.")
    name: str = Field(min_length=1, description="Its name.")
    description: str | None = None


class Extract(_Op):
    """Move nodes into a new stored workflow, and call it in their place (6.6): one node anywhere
    a step goes, or consecutive steps of one sequence, become the new workflow's root (in a
    sequence when there are several), and a `subflow` `subflow_id` that calls its version 1 takes
    their place. No reference may cross the boundary: a reduce's `from`, a publisher's
    `from_node` or a `results.<id>` in an expression. The API stores the new workflow with the
    caller's new version, both or neither. At most one per batch."""

    op: Literal["extract"]
    node_ids: list[NodeId] = Field(min_length=1, max_length=MAX_OPS)
    subflow_id: NodeId = Field(description="The id of the subflow that takes their place.")
    workflow: ExtractedWorkflow


GraphOp = Annotated[
    AddNode | RemoveNode | Connect | Disconnect | SetParam | Wrap | Extract,
    Field(discriminator="op"),
]


class GraphOps(_Op):
    """A batch of graph operations, applied in order, all or nothing."""

    ops: list[GraphOp] = Field(min_length=1, max_length=MAX_OPS)


type OpErrorCode = Literal[
    "unknown_node",
    "duplicate_node_id",
    "root_node",
    "invalid_placement",
    "slot_taken",
    "invalid_move",
    "not_in_sequence",
    "not_connected",
    "not_a_param",
    "invalid_path",
    "detached_nodes",
    "missing_child",
    "invalid_wrap",
    "invalid_extract",
    "schema",
]


class OpError(Exception):
    """Why a batch cannot apply: the op at `op_index` (`None`: the batch's result) and the node
    it is about."""

    def __init__(
        self, code: OpErrorCode, message: str, *, op_index: int | None, node_id: str | None
    ) -> None:
        super().__init__(message)
        self.code: OpErrorCode = code
        self.message = message
        self.op_index = op_index
        self.node_id = node_id


type _Json = dict[str, object]

_BODY_KINDS = ("loop", "map", "orchestrator")
"""Kinds with one `body`, which must hold a node."""

_SINGLE_SLOTS = ("body", "default")
_LIST_SLOTS = {"sequence": "steps", "parallel": "branches"}
_NODE_SLOTS = frozenset({"steps", "branches", "body", "default"})
_DOCUMENT_PARAMS = frozenset({"name", "description", "budget_usd", "input"})


@dataclass
class _Place:
    """Where a node is: `holder[key]` is it. `parent` is the node it is under (`None` at the
    root or detached); `slot` the parent's field that holds it."""

    holder: _Json | list[object]
    key: str | int
    parent: _Json | None
    slot: str | None
    detached: bool


class _Tree:
    """A spec being edited, as JSON, with the nodes detached so far."""

    def __init__(self, spec: Mapping[str, object]) -> None:
        self.doc: _Json = copy.deepcopy(dict(spec))
        self.pool: _Json = {}

    def places(self) -> Iterator[tuple[_Json, _Place]]:
        """Every node with its place, the placed ones first, depth first."""
        root = self.doc.get("root")
        if isinstance(root, dict):
            yield from _walk(cast(_Json, root), _Place(self.doc, "root", None, None, False))
        for key, node in list(self.pool.items()):
            yield from _walk(cast(_Json, node), _Place(self.pool, key, None, None, True))

    def find(self, node_id: str) -> tuple[_Json, _Place] | None:
        return next(((n, p) for n, p in self.places() if n.get("id") == node_id), None)

    def ids(self) -> set[str]:
        return {cast(str, n["id"]) for n, _ in self.places() if isinstance(n.get("id"), str)}


def _walk(node: _Json, place: _Place) -> Iterator[tuple[_Json, _Place]]:
    yield node, place
    slot = _LIST_SLOTS.get(cast(str, node.get("type")))
    if slot is not None and isinstance(found := node.get(slot), list):
        children = cast(list[object], found)
        for i, child in enumerate(children):
            if isinstance(child, dict):
                yield from _walk(
                    cast(_Json, child), _Place(children, i, node, slot, place.detached)
                )
    for slot in _SINGLE_SLOTS:
        child = node.get(slot)
        if isinstance(child, dict):
            yield from _walk(cast(_Json, child), _Place(node, slot, node, slot, place.detached))
    if node.get("type") == "router" and isinstance(routes := node.get("routes"), list):
        for item in cast(list[object], routes):
            if not isinstance(item, dict):
                continue
            route = cast(_Json, item)
            if isinstance(then := route.get("then"), dict):
                yield from _walk(
                    cast(_Json, then), _Place(route, "then", node, "then", place.detached)
                )


@dataclass(frozen=True)
class AppliedOps:
    """What a batch makes: the spec, and the workflow an `extract` moved nodes into (`None`
    without one), which the API stores as that workflow's version 1."""

    spec: dict[str, object]
    extracted: dict[str, object] | None = None


def apply_ops(spec: Mapping[str, object], ops: Sequence[GraphOp]) -> dict[str, object]:
    """`spec` (a decoded workflow document) with `ops` applied in order. `spec` is not changed.

    Raises `OpError` for the first op that cannot apply, or when the result leaves a node
    detached, a required slot empty, or is not a workflow spec (`schema`). Other issues (the
    structure, the policy) are for `validate_workflow` to report."""
    return apply_graph_ops(spec, ops).spec


def apply_graph_ops(spec: Mapping[str, object], ops: Sequence[GraphOp]) -> AppliedOps:
    """As `apply_ops`, with the workflow an `extract` made, checked as a spec too."""
    tree = _Tree(spec)
    extracted: _Json | None = None
    for index, op in enumerate(ops):
        match op:
            case AddNode():
                _add(tree, op, index)
            case RemoveNode():
                _remove(tree, op.node_id, index)
            case Connect():
                _connect(tree, op, index)
            case Disconnect():
                _disconnect(tree, op, index)
            case SetParam():
                _set_param(tree, op, index)
            case Wrap():
                _wrap(tree, op, index)
            case Extract():
                if extracted is not None:
                    raise OpError(
                        "invalid_extract",
                        "a batch may hold one extract; save, then extract again",
                        op_index=index,
                        node_id=op.node_ids[0],
                    )
                extracted = _extract(tree, op, index)
    _check_result(tree)
    if extracted is not None and (issues := schema_issues(extracted)):
        issue = issues[0]
        raise OpError(
            "schema",
            f"the extracted workflow: {issue.message}",
            op_index=None,
            node_id=issue.node_id,
        )
    return AppliedOps(tree.doc, extracted)


def _selection(
    tree: _Tree, node_ids: Sequence[str], index: int, code: OpErrorCode
) -> tuple[_Place, list[_Json]]:
    """The nodes `node_ids` name, in run order, with the place of the first: one node anywhere
    (but detached), or consecutive steps of one sequence."""

    def refuse(message: str, node_id: str) -> OpError:
        return OpError(code, message, op_index=index, node_id=node_id)

    if len(set(node_ids)) != len(node_ids):
        repeated = next(n for n in node_ids if node_ids.count(n) > 1)
        raise refuse(f"{repeated!r} is named twice", repeated)
    found = [_require(tree, node_id, index) for node_id in node_ids]
    for (_, place), node_id in zip(found, node_ids, strict=True):
        if place.detached:
            raise refuse(f"{node_id!r} is not placed in the workflow", node_id)
    if len(found) == 1:
        node, place = found[0]
        return place, [node]
    holder = found[0][1].holder
    for (_, place), node_id in zip(found, node_ids, strict=True):
        if place.slot != "steps" or place.holder is not holder:
            raise refuse(
                f"{node_id!r} is not a step of the same sequence as {node_ids[0]!r}; pick one "
                "node, or consecutive steps of one sequence",
                node_id,
            )
    ordered = sorted(found, key=lambda f: cast(int, f[1].key))
    keys = [cast(int, place.key) for _, place in ordered]
    if keys != list(range(keys[0], keys[0] + len(keys))):
        gap = cast(list[_Json], holder)[next(k + 1 for k, n in pairwise(keys) if n != k + 1)]
        raise refuse(
            f"the steps are not consecutive: {gap.get('id')!r} is between them", str(gap.get("id"))
        )
    return ordered[0][1], [node for node, _ in ordered]


def _replace(place: _Place, count: int, value: _Json) -> None:
    """Put `value` where the `count` nodes from `place` on are."""
    if count == 1:
        _set_at(place, value)
        return
    steps = cast(list[object], place.holder)
    start = cast(int, place.key)
    steps[start : start + count] = [value]


def _new_id(tree: _Tree, node_id: str, index: int) -> None:
    if node_id in tree.ids():
        raise OpError(
            "duplicate_node_id",
            f"node id {node_id!r} is already used; node ids must be unique",
            op_index=index,
            node_id=node_id,
        )


def _wrap(tree: _Tree, op: Wrap, index: int) -> None:
    place, nodes = _selection(tree, op.node_ids, index, "invalid_wrap")
    first = op.node_ids[0]

    def refuse(message: str) -> OpError:
        return OpError("invalid_wrap", message, op_index=index, node_id=first)

    container = cast(_Json, copy.deepcopy(op.with_))
    kind = container.get("type")
    container_id = container.get("id")
    if kind not in WRAP_KINDS:
        raise refuse(f"wrap puts nodes in a {', '.join(WRAP_KINDS[:-1])} or {WRAP_KINDS[-1]}")
    if not isinstance(container_id, str):
        raise refuse(f"give the new {kind} an `id`")
    if held := _NODE_SLOTS & container.keys():
        raise refuse(
            f"`with` holds no nodes ({', '.join(sorted(held))}); they are the wrapped ones"
        )
    _new_id(tree, container_id, index)
    if kind == "sequence":
        container["steps"] = nodes
    elif kind == "parallel":
        if len(nodes) < 2:
            raise refuse("a parallel needs two or more branches; wrap two or more steps")
        container["branches"] = nodes
    elif len(nodes) == 1:
        container["body"] = nodes[0]
    else:
        if op.sequence_id is None:
            raise refuse(f"give `sequence_id`: the {kind}'s body holds the steps in a sequence")
        if op.sequence_id == container_id:
            raise refuse(f"`sequence_id` and the {kind}'s id must differ")
        _new_id(tree, op.sequence_id, index)
        container["body"] = {"type": "sequence", "id": op.sequence_id, "steps": nodes}
    _replace(place, len(nodes), container)


_RESULTS = re.compile(
    r"""\bresults\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*["']([^"']+)["']\s*\])"""
)
"""A node's result named in a CEL expression: `results.fix` or `results["fix-2"]`."""


def _expressions(node: _Json) -> Iterator[str]:
    """The CEL expressions of `node` itself (not of the nodes under it)."""
    for key in ("until", "over"):
        if isinstance(value := node.get(key), str):
            yield value
    if node.get("type") == "subflow" and isinstance(value := node.get("input"), str):
        yield value
    if node.get("type") == "router":
        for route in cast(list[object], node.get("routes") or []):
            if isinstance(route, dict) and isinstance(when := cast(_Json, route).get("when"), str):
                yield when


def _references(node: _Json) -> set[str]:
    """The node ids `node` itself refers to: a reduce's `from`, a publisher's `from_node` and the
    results its expressions read."""
    found: set[str] = set()
    if node.get("type") == "reduce" and isinstance(source := node.get("from"), str):
        found.add(source)
    args = node.get("args")
    if isinstance(args, dict) and isinstance(source := cast(_Json, args).get("from_node"), str):
        found.add(source)
    for expression in _expressions(node):
        for match in _RESULTS.finditer(expression):
            found.add(match.group(1) or match.group(2))
    return found


def _in_worker(tree: _Tree, node_id: str) -> str | None:
    """The orchestrator whose worker holds the node `node_id`, if one does."""
    for node, _ in tree.places():
        body = node.get("body")
        is_worker = node.get("type") == "orchestrator" and isinstance(body, dict)
        if is_worker and node_id in _subtree_ids(cast(_Json, body)):
            return cast(str, node.get("id"))
    return None


def _extract(tree: _Tree, op: Extract, index: int) -> _Json:
    place, nodes = _selection(tree, op.node_ids, index, "invalid_extract")
    first = op.node_ids[0]

    def refuse(message: str, node_id: str = first) -> OpError:
        return OpError("invalid_extract", message, op_index=index, node_id=node_id)

    if place.holder is tree.doc:
        raise OpError(
            "root_node",
            f"{first!r} is the workflow's root; extract steps of it instead",
            op_index=index,
            node_id=first,
        )
    if op.workflow.id == tree.doc.get("id"):
        raise refuse(f"the new workflow needs an id of its own, not {op.workflow.id!r}")
    if (hub := _in_worker(tree, first)) is not None:
        raise refuse(f"{first!r} is in the worker of orchestrator {hub!r}, which runs no subflow")
    inside = {node_id for node in nodes for node_id in _subtree_ids(node)}
    for node in nodes:
        for inner, _ in _walk(node, _Place({}, "", None, None, True)):
            for ref in _references(inner) - inside:
                raise refuse(
                    f"{inner.get('id')!r} refers to {ref!r}, which stays outside; extract them "
                    "together, or change the reference first",
                    cast(str, inner.get("id")),
                )
    for outer, _ in tree.places():
        if outer.get("id") in inside:
            continue
        for ref in _references(outer) & inside:
            raise refuse(
                f"{outer.get('id')!r} refers to {ref!r}, which would move into the new workflow; "
                "extract them together, or change the reference first",
                cast(str, outer.get("id")),
            )
    if op.subflow_id in tree.ids() - inside:
        raise OpError(
            "duplicate_node_id",
            f"node id {op.subflow_id!r} is already used; node ids must be unique",
            op_index=index,
            node_id=op.subflow_id,
        )
    if len(nodes) == 1:
        root: _Json = nodes[0]
    else:
        root_id, n = "main", 2
        while root_id in inside:
            root_id, n = f"main_{n}", n + 1
        root = {"type": "sequence", "id": root_id, "steps": nodes}
    document: _Json = {"spec_version": "0", "id": op.workflow.id, "name": op.workflow.name}
    if op.workflow.description:
        document["description"] = op.workflow.description
    if (schema := _port_of(nodes[0], "input")) is not None:
        document["input_schema"] = schema
    if (schema := _port_of(nodes[-1], "output")) is not None:
        document["output_schema"] = schema
    document["root"] = root
    subflow: _Json = {
        "type": "subflow",
        "id": op.subflow_id,
        "workflow": {"id": op.workflow.id, "version": 1},
    }
    _replace(place, len(nodes), subflow)
    return copy.deepcopy(document)


def _port_of(node: _Json, side: str) -> object:
    """The `side` schema of the agent or tool node whose port is `node`'s: itself, or a
    sequence's first (input) or last (output) step, gates looked through."""
    match node.get("type"):
        case "agent" | "tool":
            return node.get(f"{side}_schema")
        case "sequence":
            steps = [
                s for s in cast(list[_Json], node.get("steps") or []) if s.get("type") != "gate"
            ]
            if not steps:
                return None
            return _port_of(steps[0] if side == "input" else steps[-1], side)
        case _:
            return None


def _node_json(node: Node) -> _Json:
    """`node` as the spec's JSON, with only the fields it was given."""
    return cast(_Json, node.model_dump(mode="json", by_alias=True, exclude_unset=True))


def _subtree_ids(node: _Json) -> list[str]:
    return [cast(str, n["id"]) for n, _ in _walk(node, _Place({}, "", None, None, True))]


def _add(tree: _Tree, op: AddNode, index: int) -> None:
    node = _node_json(op.node)
    ids = _subtree_ids(node)
    taken = tree.ids()
    seen: set[str] = set()
    for node_id in ids:
        if node_id in taken or node_id in seen:
            raise OpError(
                "duplicate_node_id",
                f"node id {node_id!r} is already used; node ids must be unique",
                op_index=index,
                node_id=node_id,
            )
        seen.add(node_id)
    if op.at is None:
        tree.pool[cast(str, node["id"])] = node
    elif isinstance(op.at, After):
        _insert_after(tree, op.at.after, node, None, index)
    else:
        _insert_into(tree, op.at, node, index)


def _require(tree: _Tree, node_id: str, index: int) -> tuple[_Json, _Place]:
    found = tree.find(node_id)
    if found is None:
        raise OpError(
            "unknown_node", f"there is no node {node_id!r}", op_index=index, node_id=node_id
        )
    return found


def _insert_after(
    tree: _Tree, after: str, node: _Json, sequence_id: str | None, index: int
) -> None:
    """Put `node` right after `after`; when `after` is not a sequence's step, wrap it in a new
    sequence `sequence_id` first (refused without one)."""
    target, place = _require(tree, after, index)
    if place.slot == "steps":
        steps = cast(list[object], place.holder)
        steps.insert(cast(int, place.key) + 1, node)
        return
    if sequence_id is None:
        raise OpError(
            "not_in_sequence",
            f"{target.get('type')} {after!r} is not a step of a sequence; give `sequence_id` to "
            "wrap it in a new sequence",
            op_index=index,
            node_id=after,
        )
    if sequence_id in tree.ids():
        raise OpError(
            "duplicate_node_id",
            f"node id {sequence_id!r} is already used; node ids must be unique",
            op_index=index,
            node_id=sequence_id,
        )
    _set_at(place, {"type": "sequence", "id": sequence_id, "steps": [target, node]})


def _set_at(place: _Place, value: object) -> None:
    if isinstance(place.holder, list):
        place.holder[cast(int, place.key)] = value
    else:
        place.holder[cast(str, place.key)] = value


def _insert_into(tree: _Tree, at: Into, node: _Json, index: int) -> None:
    parent, _ = _require(tree, at.parent, index)
    kind = parent.get("type")

    def refuse(code: OpErrorCode, message: str) -> OpError:
        return OpError(code, message, op_index=index, node_id=at.parent)

    if kind in _LIST_SLOTS:
        if at.route is not None:
            raise refuse("invalid_placement", f"{kind} {at.parent!r} has no routes")
        children = cast(list[object], parent[_LIST_SLOTS[cast(str, kind)]])
        position = len(children) if at.index is None else at.index
        if position > len(children):
            raise refuse(
                "invalid_placement",
                f"{kind} {at.parent!r} has {len(children)} children; index {position} is past "
                "the end",
            )
        children.insert(position, node)
        return
    if at.index is not None:
        raise refuse("invalid_placement", f"`index` is for sequences and parallels, not a {kind}")
    if kind in _BODY_KINDS:
        if at.route is not None:
            raise refuse("invalid_placement", f"{kind} {at.parent!r} has no routes")
        if parent.get("body") is not None:
            raise refuse("slot_taken", f"{kind} {at.parent!r} already has a body; remove it first")
        parent["body"] = node
        return
    if kind == "router":
        if at.route is None:
            raise refuse("invalid_placement", f"give the `route` of router {at.parent!r}")
        if at.route == DEFAULT_ROUTE:
            holder, label = parent, "its default"
            key = "default"
        else:
            routes = cast(list[_Json], parent.get("routes") or [])
            route = next((r for r in routes if r.get("id") == at.route), None)
            if route is None:
                raise refuse("invalid_placement", f"router {at.parent!r} has no route {at.route!r}")
            holder, label, key = route, f"route {at.route!r}", "then"
        if holder.get(key) is not None:
            raise refuse(
                "slot_taken", f"router {at.parent!r} already has a node on {label}; remove it first"
            )
        holder[key] = node
        return
    raise refuse("invalid_placement", f"{kind} {at.parent!r} holds no nodes")


def _take_out(tree: _Tree, node_id: str, index: int) -> _Json:
    """Remove the node `node_id` from where it is, leaving an empty slot behind if it was a
    body or a route's `then`; a removed `default` is simply gone."""
    node, place = _require(tree, node_id, index)
    if place.holder is tree.doc:
        raise OpError(
            "root_node",
            f"{node_id!r} is the workflow's root; it cannot be removed or moved",
            op_index=index,
            node_id=node_id,
        )
    if isinstance(place.holder, list):
        del place.holder[cast(int, place.key)]
    elif place.holder is tree.pool or place.key == "default":
        del place.holder[cast(str, place.key)]
    else:
        place.holder[cast(str, place.key)] = None
    return node


def _remove(tree: _Tree, node_id: str, index: int) -> None:
    _take_out(tree, node_id, index)


def _connect(tree: _Tree, op: Connect, index: int) -> None:
    if op.to == op.from_:
        raise OpError(
            "invalid_move", f"{op.to!r} cannot follow itself", op_index=index, node_id=op.to
        )
    to, _ = _require(tree, op.to, index)
    _require(tree, op.from_, index)
    if op.from_ in _subtree_ids(to):
        raise OpError(
            "invalid_move",
            f"{op.from_!r} is inside {op.to!r}, so {op.to!r} cannot follow it",
            op_index=index,
            node_id=op.to,
        )
    _take_out(tree, op.to, index)
    _insert_after(tree, op.from_, to, op.sequence_id, index)


def _disconnect(tree: _Tree, op: Disconnect, index: int) -> None:
    _, from_place = _require(tree, op.from_, index)
    _, to_place = _require(tree, op.to, index)
    if (
        from_place.slot != "steps"
        or to_place.holder is not from_place.holder
        or to_place.key != cast(int, from_place.key) + 1
    ):
        raise OpError(
            "not_connected",
            f"{op.to!r} is not the step right after {op.from_!r}",
            op_index=index,
            node_id=op.to,
        )
    tree.pool[op.to] = _take_out(tree, op.to, index)


_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\[\d+\]")
_PATH_SHAPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*")


def _parse_path(path: str, index: int, node_id: str | None) -> list[str | int]:
    if not _PATH_SHAPE.fullmatch(path):
        raise OpError(
            "invalid_path",
            f"{path!r} is not a parameter path; use field names, `.` and `[index]`, e.g. "
            "`routes[1].when`",
            op_index=index,
            node_id=node_id,
        )
    return [int(p[1:-1]) if p.startswith("[") else p for p in _PATH.findall(path)]


def _set_param(tree: _Tree, op: SetParam, index: int) -> None:
    parts = _parse_path(op.path, index, op.node_id)
    if op.node_id is None:
        target = tree.doc
        allowed = parts[0] in _DOCUMENT_PARAMS
        what = "the document"
    else:
        target, _ = _require(tree, op.node_id, index)
        allowed = _is_param(cast(str, target.get("type")), parts)
        what = f"{target.get('type')} {op.node_id!r}"
    if not allowed:
        raise OpError(
            "not_a_param",
            f"{op.path!r} is not a parameter of {what}: ids, types and the nodes it holds "
            "change through addNode, removeNode, connect and disconnect",
            op_index=index,
            node_id=op.node_id,
        )

    def bad_path(reason: str) -> OpError:
        return OpError(
            "invalid_path", f"{op.path!r} on {what}: {reason}", op_index=index, node_id=op.node_id
        )

    container: object = target
    for part, following in pairwise(parts):
        container = _step_into(container, part, following, bad_path)
    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(container, list) or last >= len(cast(list[object], container)):
            raise bad_path(f"there is no item {last}")
        if op.value is None:
            raise bad_path("an item cannot be unset; set the whole list")
        cast(list[object], container)[last] = op.value
    elif not isinstance(container, dict):
        raise bad_path(f"{last!r} is not inside an object")
    elif op.value is None:
        cast(_Json, container).pop(last, None)
    else:
        cast(_Json, container)[last] = copy.deepcopy(op.value)


def _is_param(kind: str, parts: list[str | int]) -> bool:
    """Whether `parts` names a parameter of a `kind` node, not its id, type or a node in it."""
    head = parts[0]
    if head in ("id", "type") or head in _NODE_SLOTS:
        return False
    if kind == "router" and head == "routes":
        # A route's `when`, `description` and `id` (not a node id) are parameters; the list
        # itself, a whole route and its `then` hold nodes.
        return len(parts) >= 3 and parts[2] != "then"
    return True


def _step_into(
    container: object, part: str | int, following: str | int, bad_path: Callable[[str], OpError]
) -> object:
    """`container[part]`, made an empty object or list (as `following` needs) when unset."""
    if isinstance(part, int):
        if not isinstance(container, list) or part >= len(cast(list[object], container)):
            raise bad_path(f"there is no item {part}")
        return cast(list[object], container)[part]
    if not isinstance(container, dict):
        raise bad_path(f"{part!r} is not inside an object")
    holder = cast(_Json, container)
    if holder.get(part) is None:
        holder[part] = [] if isinstance(following, int) else {}
    return holder[part]


def _check_result(tree: _Tree) -> None:
    if tree.pool:
        node_id = cast(str, cast(_Json, next(iter(tree.pool.values())))["id"])
        raise OpError(
            "detached_nodes",
            f"{node_id!r} is not placed in the workflow; connect it or remove it",
            op_index=None,
            node_id=node_id,
        )
    for node, _ in tree.places():
        kind = node.get("type")
        if kind in _BODY_KINDS and node.get("body") is None:
            _missing(node, "has no body")
        if kind == "router":
            for route in cast(list[_Json], node.get("routes") or []):
                if route.get("then") is None:
                    _missing(node, f"has nothing on route {route.get('id')!r}")
    if issues := schema_issues(tree.doc):
        issue = issues[0]
        more = f" (and {len(issues) - 1} more)" if len(issues) > 1 else ""
        raise OpError("schema", issue.message + more, op_index=None, node_id=issue.node_id)


def _missing(node: _Json, what: str) -> None:
    raise OpError(
        "missing_child",
        f"{node.get('type')} {node.get('id')!r} {what}; add a node there",
        op_index=None,
        node_id=cast(str | None, node.get("id")),
    )
