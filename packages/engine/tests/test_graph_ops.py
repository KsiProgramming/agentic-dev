import copy
from typing import Any

import pytest
from pydantic import TypeAdapter

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import GraphOp, OpError, apply_ops, schema_issues, validate_workflow

OPS: TypeAdapter[list[GraphOp]] = TypeAdapter(list[GraphOp])


def agent(node_id: str) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": node_id, "instructions": f"Do {node_id}."}


def spec(root: dict[str, Any]) -> dict[str, Any]:
    return {"spec_version": "0", "id": "flow", "name": "Flow", "root": root}


def seq(node_id: str, *steps: dict[str, Any]) -> dict[str, Any]:
    return {"type": "sequence", "id": node_id, "steps": list(steps)}


def loop(node_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"type": "loop", "id": node_id, "body": body, "until": "true", "max_iterations": 2}


def router(node_id: str, **routes: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "router",
        "id": node_id,
        "routes": [{"id": r, "when": "true", "then": then} for r, then in routes.items()],
    }


def apply(doc: dict[str, Any], *ops: dict[str, Any]) -> dict[str, Any]:
    result = apply_ops(doc, OPS.validate_python(list(ops)))
    assert schema_issues(result) == []  # every result is a workflow spec
    return result


def refused(doc: dict[str, Any], *ops: dict[str, Any]) -> OpError:
    before = copy.deepcopy(doc)
    with pytest.raises(OpError) as exc:
        apply_ops(doc, OPS.validate_python(list(ops)))
    assert doc == before  # all or nothing: the input is never changed
    return exc.value


def step_ids(node: dict[str, Any]) -> list[str]:
    return [step["id"] for step in node["steps"]]


BASE = spec(seq("main", agent("a"), agent("b"), agent("c")))


# addNode


def test_add_node_at_index_and_after() -> None:
    first = apply(BASE, {"op": "addNode", "node": agent("x"), "at": {"parent": "main", "index": 0}})
    assert step_ids(first["root"]) == ["x", "a", "b", "c"]

    after = apply(BASE, {"op": "addNode", "node": agent("x"), "at": {"after": "b"}})
    assert step_ids(after["root"]) == ["a", "b", "x", "c"]

    last = apply(BASE, {"op": "addNode", "node": agent("x"), "at": {"parent": "main"}})
    assert step_ids(last["root"]) == ["a", "b", "c", "x"]


def test_add_node_keeps_only_given_fields() -> None:
    result = apply(BASE, {"op": "addNode", "node": agent("x"), "at": {"after": "c"}})
    assert result["root"]["steps"][3] == agent("x")


def test_add_parallel_branch() -> None:
    doc = spec(
        seq(
            "main",
            {"type": "parallel", "id": "p", "join": "all", "branches": [agent("a"), agent("b")]},
        )
    )
    result = apply(doc, {"op": "addNode", "node": agent("x"), "at": {"parent": "p", "index": 1}})
    assert [b["id"] for b in result["root"]["steps"][0]["branches"]] == ["a", "x", "b"]


def test_add_container_with_children() -> None:
    result = apply(BASE, {"op": "addNode", "node": loop("l", agent("x")), "at": {"after": "a"}})
    assert result["root"]["steps"][1]["body"]["id"] == "x"


def test_replace_loop_body_in_one_batch() -> None:
    doc = spec(seq("main", loop("l", agent("a"))))
    result = apply(
        doc,
        {"op": "removeNode", "node_id": "a"},
        {"op": "addNode", "node": agent("x"), "at": {"parent": "l"}},
    )
    assert result["root"]["steps"][0]["body"]["id"] == "x"


def test_add_router_route_and_default() -> None:
    doc = spec(seq("main", router("r", odd=agent("a"))))
    result = apply(
        doc,
        {"op": "removeNode", "node_id": "a"},
        {"op": "addNode", "node": agent("x"), "at": {"parent": "r", "route": "odd"}},
        {"op": "addNode", "node": agent("y"), "at": {"parent": "r", "route": "default"}},
    )
    routed = result["root"]["steps"][0]
    assert routed["routes"][0]["then"]["id"] == "x"
    assert routed["default"]["id"] == "y"


def test_detached_node_is_connected_in_the_same_batch() -> None:
    result = apply(
        BASE,
        {"op": "addNode", "node": agent("x")},
        {"op": "connect", "from": "a", "to": "x"},
    )
    assert step_ids(result["root"]) == ["a", "x", "b", "c"]


@pytest.mark.parametrize(
    ("op", "code", "node_id"),
    [
        ({"op": "addNode", "node": agent("b"), "at": {"after": "a"}}, "duplicate_node_id", "b"),
        (
            {"op": "addNode", "node": seq("s", agent("x"), agent("x")), "at": {"after": "a"}},
            "duplicate_node_id",
            "x",
        ),
        ({"op": "addNode", "node": agent("x"), "at": {"after": "nope"}}, "unknown_node", "nope"),
        (
            {"op": "addNode", "node": agent("x"), "at": {"parent": "a"}},
            "invalid_placement",
            "a",
        ),
        (
            {"op": "addNode", "node": agent("x"), "at": {"parent": "main", "index": 9}},
            "invalid_placement",
            "main",
        ),
        (
            {"op": "addNode", "node": agent("x"), "at": {"parent": "main", "route": "odd"}},
            "invalid_placement",
            "main",
        ),
    ],
)
def test_add_node_refused(op: dict[str, Any], code: str, node_id: str) -> None:
    error = refused(BASE, op)
    assert (error.code, error.op_index, error.node_id) == (code, 0, node_id)


def test_add_into_taken_slots_is_refused() -> None:
    doc = spec(seq("main", loop("l", agent("a")), router("r", odd=agent("b"))))
    body = refused(doc, {"op": "addNode", "node": agent("x"), "at": {"parent": "l"}})
    assert body.code == "slot_taken"
    route = refused(
        doc, {"op": "addNode", "node": agent("x"), "at": {"parent": "r", "route": "odd"}}
    )
    assert route.code == "slot_taken"
    unknown = refused(
        doc, {"op": "addNode", "node": agent("x"), "at": {"parent": "r", "route": "x"}}
    )
    assert unknown.code == "invalid_placement"
    no_route = refused(doc, {"op": "addNode", "node": agent("x"), "at": {"parent": "r"}})
    assert no_route.code == "invalid_placement"


def test_add_after_a_node_outside_a_sequence_is_refused() -> None:
    doc = spec(seq("main", loop("l", agent("a"))))
    error = refused(doc, {"op": "addNode", "node": agent("x"), "at": {"after": "a"}})
    assert error.code == "not_in_sequence"


# removeNode


def test_remove_step_joins_neighbours() -> None:
    result = apply(BASE, {"op": "removeNode", "node_id": "b"})
    assert step_ids(result["root"]) == ["a", "c"]


def test_remove_container_removes_its_subtree() -> None:
    doc = spec(seq("main", agent("a"), loop("l", seq("inner", agent("x"), agent("y")))))
    result = apply(
        doc,
        {"op": "removeNode", "node_id": "l"},
        {"op": "addNode", "node": agent("x"), "at": {"after": "a"}},  # its ids are free again
    )
    assert step_ids(result["root"]) == ["a", "x"]


def test_remove_router_default() -> None:
    doc = spec(seq("main", {**router("r", odd=agent("a")), "default": agent("d")}))
    result = apply(doc, {"op": "removeNode", "node_id": "d"})
    assert "default" not in result["root"]["steps"][0]


def test_remove_detached_node() -> None:
    result = apply(
        BASE,
        {"op": "addNode", "node": agent("x")},
        {"op": "removeNode", "node_id": "x"},
    )
    assert result == BASE


def test_remove_root_is_refused() -> None:
    error = refused(BASE, {"op": "removeNode", "node_id": "main"})
    assert (error.code, error.node_id) == ("root_node", "main")


def test_remove_loop_body_leaves_it_missing() -> None:
    doc = spec(seq("main", loop("l", agent("a"))))
    error = refused(doc, {"op": "removeNode", "node_id": "a"})
    assert (error.code, error.op_index, error.node_id) == ("missing_child", None, "l")
    assert "has no body" in error.message


def test_remove_route_then_leaves_it_missing() -> None:
    doc = spec(seq("main", router("r", odd=agent("a"))))
    error = refused(doc, {"op": "removeNode", "node_id": "a"})
    assert (error.code, error.node_id) == ("missing_child", "r")


def test_remove_last_step_is_a_schema_error() -> None:
    doc = spec(seq("main", seq("inner", agent("a"))))
    error = refused(doc, {"op": "removeNode", "node_id": "a"})
    assert error.code == "schema"
    assert error.node_id == "inner"


# connect


def test_connect_moves_a_node_with_its_subtree() -> None:
    doc = spec(seq("main", agent("a"), loop("l", agent("x")), agent("c")))
    result = apply(doc, {"op": "connect", "from": "c", "to": "l"})
    assert step_ids(result["root"]) == ["a", "c", "l"]
    assert result["root"]["steps"][2]["body"]["id"] == "x"


def test_connect_across_containers() -> None:
    doc = spec(seq("main", agent("a"), loop("l", seq("body", agent("x"))), agent("c")))
    result = apply(doc, {"op": "connect", "from": "x", "to": "c"})
    assert step_ids(result["root"]) == ["a", "l"]
    assert step_ids(result["root"]["steps"][1]["body"]) == ["x", "c"]


def test_connect_wraps_a_node_outside_a_sequence() -> None:
    doc = spec(seq("main", loop("l", agent("a"))))
    result = apply(
        doc,
        {"op": "addNode", "node": agent("x")},
        {"op": "connect", "from": "a", "to": "x", "sequence_id": "revise"},
    )
    body = result["root"]["steps"][0]["body"]
    assert body["type"] == "sequence"
    assert (body["id"], step_ids(body)) == ("revise", ["a", "x"])


def test_connect_outside_a_sequence_needs_a_sequence_id() -> None:
    doc = spec(seq("main", loop("l", agent("a"))))
    error = refused(
        doc, {"op": "addNode", "node": agent("x")}, {"op": "connect", "from": "a", "to": "x"}
    )
    assert (error.code, error.op_index, error.node_id) == ("not_in_sequence", 1, "a")


def test_connect_wrap_with_a_used_id_is_refused() -> None:
    doc = spec(seq("main", loop("l", agent("a"))))
    error = refused(
        doc,
        {"op": "addNode", "node": agent("x")},
        {"op": "connect", "from": "a", "to": "x", "sequence_id": "main"},
    )
    assert error.code == "duplicate_node_id"


@pytest.mark.parametrize(
    ("op", "code"),
    [
        ({"op": "connect", "from": "a", "to": "a"}, "invalid_move"),
        ({"op": "connect", "from": "a", "to": "main"}, "invalid_move"),  # main holds a
        ({"op": "connect", "from": "a", "to": "nope"}, "unknown_node"),
        ({"op": "connect", "from": "nope", "to": "a"}, "unknown_node"),
    ],
)
def test_connect_refused(op: dict[str, Any], code: str) -> None:
    assert refused(BASE, op).code == code


def test_connect_into_its_own_subtree_is_refused() -> None:
    doc = spec(seq("main", seq("outer", agent("a"), agent("b")), agent("c")))
    error = refused(doc, {"op": "connect", "from": "a", "to": "outer"})
    assert (error.code, error.node_id) == ("invalid_move", "outer")


# disconnect


def test_disconnect_then_reconnect_elsewhere() -> None:
    result = apply(
        BASE,
        {"op": "disconnect", "from": "a", "to": "b"},
        {"op": "connect", "from": "c", "to": "b"},
    )
    assert step_ids(result["root"]) == ["a", "c", "b"]


def test_disconnect_and_remove() -> None:
    result = apply(
        BASE,
        {"op": "disconnect", "from": "a", "to": "b"},
        {"op": "removeNode", "node_id": "b"},
    )
    assert step_ids(result["root"]) == ["a", "c"]


def test_disconnected_node_left_detached_is_refused() -> None:
    error = refused(BASE, {"op": "disconnect", "from": "a", "to": "b"})
    assert (error.code, error.op_index, error.node_id) == ("detached_nodes", None, "b")


@pytest.mark.parametrize(("from_", "to"), [("a", "c"), ("b", "a"), ("main", "a")])
def test_disconnect_of_steps_not_in_order_is_refused(from_: str, to: str) -> None:
    error = refused(BASE, {"op": "disconnect", "from": from_, "to": to})
    assert (error.code, error.node_id) == ("not_connected", to)


# setParam


def test_set_and_unset_params() -> None:
    result = apply(
        BASE,
        {"op": "setParam", "node_id": "a", "path": "instructions", "value": "New."},
        {"op": "setParam", "node_id": "a", "path": "model", "value": "claude-sonnet-5-5"},
        {"op": "setParam", "node_id": "b", "path": "tools", "value": ["repo.read_file"]},
        {"op": "setParam", "node_id": "a", "path": "model", "value": None},
        {"op": "setParam", "path": "name", "value": "Renamed"},
    )
    a, b, _ = result["root"]["steps"]
    assert a == {**agent("a"), "instructions": "New."}
    assert b["tools"] == ["repo.read_file"]
    assert result["name"] == "Renamed"


def test_set_nested_params() -> None:
    doc = spec(seq("main", router("r", odd=agent("a"), even=agent("b"))))
    result = apply(
        doc,
        {"op": "setParam", "node_id": "r", "path": "routes[1].when", "value": "false"},
        {"op": "setParam", "node_id": "r", "path": "routes[0].description", "value": "Odd."},
    )
    routes = result["root"]["steps"][0]["routes"]
    assert routes[1]["when"] == "false"
    assert routes[0]["description"] == "Odd."


def test_set_param_creates_a_missing_object() -> None:
    doc = spec(
        seq(
            "main",
            {
                "type": "router",
                "id": "r",
                "routes": [{"id": "odd", "then": agent("a")}],
                "classifier": {"instructions": "Pick."},
            },
        )
    )
    result = apply(
        doc,
        {"op": "setParam", "node_id": "r", "path": "classifier.model", "value": "claude-haiku-5-5"},
    )
    assert result["root"]["steps"][0]["classifier"]["model"] == "claude-haiku-5-5"


@pytest.mark.parametrize(
    ("node_id", "path", "code"),
    [
        ("a", "id", "not_a_param"),
        ("a", "type", "not_a_param"),
        ("main", "steps", "not_a_param"),
        ("main", "steps[0].role", "not_a_param"),
        ("r", "routes", "not_a_param"),
        ("r", "routes[0]", "not_a_param"),
        ("r", "routes[0].then", "not_a_param"),
        ("r", "routes[0].then.role", "not_a_param"),
        (None, "id", "not_a_param"),
        (None, "root", "not_a_param"),
        ("a", "routes..when", "invalid_path"),
        ("a", "1abc", "invalid_path"),
        ("r", "routes[5].when", "invalid_path"),
        ("a", "role.x", "invalid_path"),
        ("nope", "role", "unknown_node"),
    ],
)
def test_set_param_refused(node_id: str | None, path: str, code: str) -> None:
    doc = spec(seq("main", agent("a"), router("r", odd=agent("b"))))
    error = refused(doc, {"op": "setParam", "node_id": node_id, "path": path, "value": "x"})
    assert error.code == code
    assert error.op_index == 0


def test_set_param_off_the_schema_is_refused() -> None:
    error = refused(BASE, {"op": "setParam", "node_id": "a", "path": "role", "value": 3})
    assert (error.code, error.op_index, error.node_id) == ("schema", None, "a")


# a batch


def test_failing_op_names_its_index_and_changes_nothing() -> None:
    error = refused(
        BASE,
        {"op": "addNode", "node": agent("x"), "at": {"after": "a"}},
        {"op": "removeNode", "node_id": "b"},
        {"op": "removeNode", "node_id": "nope"},
    )
    assert (error.code, error.op_index) == ("unknown_node", 2)


def test_result_may_have_structure_issues() -> None:
    # Only the schema is enforced: a gate inside a loop is for `validate_workflow` to report,
    # and the canvas shows it.
    doc = spec(seq("main", loop("l", agent("a"))))
    gate = {"type": "gate", "id": "g", "title": "Go?"}
    result = apply(
        doc,
        {"op": "addNode", "node": gate},
        {"op": "connect", "from": "a", "to": "g", "sequence_id": "s"},
    )
    issues = validate_workflow(
        result, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="claude-sonnet-5-5"
    )
    assert [issue.code for issue in issues] == ["not_allowed_in_loop"]
    assert result["root"]["steps"][0]["body"]["steps"][1]["id"] == "g"
