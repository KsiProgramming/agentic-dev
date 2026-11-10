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


GraphOp = Annotated[
    AddNode | RemoveNode | Connect | Disconnect | SetParam, Field(discriminator="op")
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


def apply_ops(spec: Mapping[str, object], ops: Sequence[GraphOp]) -> dict[str, object]:
    """`spec` (a decoded workflow document) with `ops` applied in order. `spec` is not changed.

    Raises `OpError` for the first op that cannot apply, or when the result leaves a node
    detached, a required slot empty, or is not a workflow spec (`schema`). Other issues (the
    structure, the policy) are for `validate_workflow` to report."""
    tree = _Tree(spec)
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
    _check_result(tree)
    return tree.doc


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
