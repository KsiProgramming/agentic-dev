"""The `orchestrator` primitive's spec (6.1): its model, the plan schema, the rules for its body
and placement, publishing, policy and the writers it makes per task."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.ports import check_port
from agentic_engine.spec import (
    MAX_AGENTS_SPAWNED,
    MAX_REPLAN_ROUNDS,
    OrchestratorNode,
    ValidationIssue,
    WorkflowSpec,
    agents_spawned,
    orchestrator_plan_schema,
    task_node_ids,
    task_writer_key,
    task_writer_orchestrator,
    task_writer_orchestrators,
    validate_workflow,
    writer_node_ids,
)


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **fields}


def orchestrator(body: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {
        "type": "orchestrator",
        "id": "fix",
        "hub": {"role": "Lead", "instructions": "Plan the fixes."},
        "body": body,
        "max_workers": 4,
        "max_concurrency": 2,
        **fields,
    }


def workflow(root: dict[str, Any]) -> dict[str, Any]:
    return {"spec_version": "0", "id": "wf", "name": "Workflow", "root": root}


def validate(root: dict[str, Any], **policy: int) -> list[ValidationIssue]:
    return validate_workflow(
        workflow(root),
        policy=PLATFORM_POLICY.model_copy(update=policy),
        priced=lambda _: True,
        default_model="default",
    )


def where(issues: list[ValidationIssue]) -> list[tuple[str, str, str | None]]:
    return [(issue.code, issue.path, issue.node_id) for issue in issues]


def test_an_orchestrator_with_an_agent_worker_is_valid() -> None:
    assert validate(orchestrator(agent("worker"))) == []


def test_a_worker_may_be_a_sequence_of_agents_and_tools_and_may_write() -> None:
    body = {
        "type": "sequence",
        "id": "work",
        "steps": [
            {"type": "tool", "id": "look", "tool": "repo.list_files"},
            agent("fixer", tools=["repo.read_file", "repo.write_file", "repo.commit"]),
        ],
    }
    assert validate(orchestrator(body)) == []


@pytest.mark.parametrize(
    ("max_workers", "max_concurrency"),
    [(0, 1), (MAX_AGENTS_SPAWNED + 1, 1), (2, 0), (2, PLATFORM_POLICY.agents_alive + 1)],
)
def test_worker_counts_are_bounded(max_workers: int, max_concurrency: int) -> None:
    node = orchestrator(agent("w"), max_workers=max_workers, max_concurrency=max_concurrency)
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(workflow(node))


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({"type": "gate", "id": "approve", "title": "OK?"}, "gate"),
        (
            {
                "type": "loop",
                "id": "again",
                "body": agent("w"),
                "until": "true",
                "max_iterations": 2,
            },
            "loop",
        ),
        (
            {
                "type": "map",
                "id": "each",
                "over": "[last]",
                "body": agent("w"),
                "max_concurrency": 2,
            },
            "map",
        ),
        (
            {"type": "parallel", "id": "both", "join": "all", "branches": [agent("a"), agent("b")]},
            "parallel",
        ),
        (
            {
                "type": "router",
                "id": "pick",
                "routes": [{"id": "one", "when": "true", "then": agent("w")}],
            },
            "router",
        ),
        (
            {
                "type": "tool",
                "id": "publish",
                "tool": "github.openPR",
                "args": {"from_node": "x"},
            },
            "publisher",
        ),
        ({"type": "tool", "id": "create", "tool": "github.createRepo"}, "repo creator"),
    ],
    ids=lambda v: v if isinstance(v, str) else v["type"],
)
def test_a_worker_holds_only_agents_tools_and_sequences(body: dict[str, Any], reason: str) -> None:
    issues = [i for i in validate(orchestrator(body)) if i.code == "not_allowed_in_orchestrator"]
    assert where(issues)[:1] == [("not_allowed_in_orchestrator", "root.body", body["id"])]
    assert f"{reason} {body['id']!r} at root.body cannot be inside an orchestrator" in (
        issues[0].message
    )


def test_an_orchestrator_cannot_nest_in_another() -> None:
    inner = orchestrator(agent("w"), id="inner")
    issues = validate(orchestrator(inner))
    assert ("not_allowed_in_orchestrator", "root.body", "inner") in where(issues)


@pytest.mark.parametrize(
    ("root", "code", "path"),
    [
        (
            {
                "type": "map",
                "id": "each",
                "over": "[last]",
                "body": orchestrator(agent("w")),
                "max_concurrency": 2,
            },
            "not_allowed_in_map",
            "root.body",
        ),
        (
            {
                "type": "parallel",
                "id": "both",
                "join": "all",
                "branches": [orchestrator(agent("w")), agent("b")],
            },
            "not_allowed_in_parallel",
            "root.branches[0]",
        ),
    ],
    ids=["map", "parallel"],
)
def test_an_orchestrator_cannot_run_per_item_or_branch(
    root: dict[str, Any], code: str, path: str
) -> None:
    assert (code, path, "fix") in where(validate(root))


LOOP_WRITER = agent("w", tools=["repo.write_file"])
OPEN_PR = {"type": "tool", "id": "open_pr", "tool": "github.openPR", "args": {"from_node": "fix"}}


def review_loop(*more: dict[str, Any]) -> dict[str, Any]:
    """A loop around a writing orchestrator and a reviewer (6.9)."""
    return {
        "type": "loop",
        "id": "again",
        "body": {
            "type": "sequence",
            "id": "round",
            "steps": [orchestrator(LOOP_WRITER), agent("reviewer"), *more],
        },
        "until": 'last.contains("OK")',
        "max_iterations": 3,
    }


def test_an_orchestrator_whose_worker_writes_may_be_in_a_loop() -> None:
    assert validate(review_loop()) == []


def test_a_gate_and_a_publish_after_the_loop_see_its_orchestrator() -> None:
    root = {
        "type": "sequence",
        "id": "main",
        "steps": [
            review_loop(),
            {"type": "gate", "id": "approve", "title": "Approve"},
            OPEN_PR,
        ],
    }
    assert validate(root) == []


def test_a_publish_after_the_loop_still_needs_a_gate() -> None:
    root = {
        "type": "sequence",
        "id": "main",
        "steps": [
            review_loop(),
            OPEN_PR,
        ],
    }
    assert ("publish_without_gate", "root.steps[1]", "open_pr") in where(validate(root))


@pytest.mark.parametrize(
    ("node", "path"),
    [
        (agent("plain", tools=["repo.write_file"]), "root.body.steps[2]"),
        ({"type": "gate", "id": "plain", "title": "Check"}, "root.body.steps[2]"),
        (
            {"type": "tool", "id": "plain", "tool": "github.openPR", "args": {"from_node": "fix"}},
            "root.body.steps[2]",
        ),
    ],
    ids=["writer", "gate", "publisher"],
)
def test_a_plain_writer_gate_or_publisher_in_the_loop_is_still_refused(
    node: dict[str, Any], path: str
) -> None:
    assert ("not_allowed_in_loop", path, "plain") in where(validate(review_loop(node)))


def test_an_orchestrator_in_a_loop_still_cannot_be_in_a_map_inside_it() -> None:
    root = {
        "type": "loop",
        "id": "again",
        "body": {
            "type": "map",
            "id": "each",
            "over": "[last]",
            "body": orchestrator(agent("w")),
            "max_concurrency": 2,
        },
        "until": "true",
        "max_iterations": 2,
    }
    codes = where(validate(root))
    assert ("not_allowed_in_map", "root.body.body", "fix") in codes


def test_an_orchestrator_may_be_on_a_route_at_the_top_of_the_run() -> None:
    root = {
        "type": "router",
        "id": "pick",
        "routes": [
            {
                "id": "fix_it",
                "when": "true",
                "then": {"type": "sequence", "id": "fixing", "steps": [orchestrator(agent("w"))]},
            }
        ],
    }
    assert validate(root) == []


def test_a_reduce_combines_an_orchestrator() -> None:
    root = {
        "type": "sequence",
        "id": "main",
        "steps": [
            orchestrator(agent("w")),
            {"type": "reduce", "id": "join", "from": "fix", "strategy": "concat"},
        ],
    }
    assert validate(root) == []


def publishing(source: str, body: dict[str, Any], gate: bool = True) -> dict[str, Any]:
    """An orchestrator over `body`, a gate unless `gate` is false, then `openPR` from `source`."""
    steps: list[dict[str, Any]] = [orchestrator(body)]
    if gate:
        steps.append({"type": "gate", "id": "approve", "title": "Publish?"})
    steps.append(
        {
            "type": "tool",
            "id": "publish",
            "tool": "github.openPR",
            "args": {"from_node": source, "title": "Fixes"},
        }
    )
    return {"type": "sequence", "id": "main", "steps": steps}


WRITER = agent("fixer", tools=["repo.write_file", "repo.commit"])


def test_the_orchestrator_publishes_its_integration_branch_after_a_gate() -> None:
    assert validate(publishing("fix", WRITER)) == []


def test_publishing_the_orchestrator_needs_a_gate() -> None:
    issues = validate(publishing("fix", WRITER, gate=False))
    assert where(issues) == [("publish_without_gate", "root.steps[1]", "publish")]


def test_publishing_a_worker_names_its_orchestrator_instead() -> None:
    issues = validate(publishing("fixer", WRITER))
    assert where(issues) == [("reference", "root.steps[2]", "publish")]
    assert "is a worker of 'fix'" in issues[0].message
    assert "publish 'fix', its integration branch, instead" in issues[0].message


def test_an_orchestrator_whose_tasks_do_not_write_has_nothing_to_publish() -> None:
    issues = validate(publishing("fix", agent("reader", tools=["repo.read_file"])))
    assert where(issues) == [("reference", "root.steps[2]", "publish")]
    assert "is not a writer" in issues[0].message


def test_a_worker_cannot_write_an_artifact_but_the_orchestrator_can() -> None:
    assert where(validate(orchestrator(agent("w", writes="notes.md")))) == [
        ("artifact_conflict", "root.body", "w")
    ]
    root = {
        "type": "sequence",
        "id": "main",
        "steps": [
            orchestrator(agent("w"), writes="notes.md"),
            agent("summary", reads=["notes.md"]),
        ],
    }
    assert validate(root) == []


def test_policy_holds_concurrency_and_depth() -> None:
    issues = validate(orchestrator(agent("w"), max_concurrency=6), agents_alive=4)
    assert [(i.code, i.limit, i.value, i.observed) for i in issues] == [
        ("policy_limit", "agents_alive", 4, 6)
    ]
    nested = {
        "type": "loop",
        "id": "outer",
        "until": "true",
        "max_iterations": 2,
        "body": agent("w"),
    }
    root = {"type": "sequence", "id": "main", "steps": [nested, orchestrator(agent("x"))]}
    assert validate(root, max_depth=1) == []
    assert [i.limit for i in validate(orchestrator(agent("x")), max_depth=0)] == ["max_depth"]


def test_a_hub_on_an_unpriced_model_cannot_hold_a_budget() -> None:
    node = orchestrator(agent("w", model="cheap"))
    node["hub"]["model"] = "unknown"
    issues = validate_workflow(
        workflow(node),
        policy=PLATFORM_POLICY.model_copy(update={"budget_usd": 5}),
        priced=lambda model: model == "cheap",
        default_model="cheap",
    )
    assert where(issues) == [("budget_unpriced_model", "root", "fix")]


def test_only_the_hub_counts_before_the_plan() -> None:
    spec = WorkflowSpec.model_validate(workflow(orchestrator(agent("w"))))
    assert agents_spawned(spec.root) == 1


def test_writers_in_a_worker_write_per_task() -> None:
    writer = agent("fixer", tools=["repo.write_file"])
    root = {
        "type": "sequence",
        "id": "main",
        "steps": [agent("plain", tools=["repo.write_file"]), orchestrator(writer)],
    }
    spec = WorkflowSpec.model_validate(workflow(root))
    assert writer_node_ids(spec.root) == {"plain"}
    assert task_writer_orchestrators(spec.root) == {"fix"}
    assert task_node_ids(spec.root) == {"fix", "fixer"}
    reader = WorkflowSpec.model_validate(workflow(orchestrator(agent("w"))))
    assert task_writer_orchestrators(reader.root) == set()


def test_a_task_writer_key_names_its_orchestrator() -> None:
    key = task_writer_key("fix", "t1")
    assert key == "fix.t1"
    assert task_writer_orchestrator(key) == "fix"
    assert task_writer_orchestrator("fix") is None


def test_the_plan_schema_bounds_the_tasks() -> None:
    node = OrchestratorNode.model_validate(orchestrator(agent("w"), max_workers=2))
    schema = orchestrator_plan_schema(node)

    def task(task_id: str) -> dict[str, str]:
        return {"id": task_id, "title": f"Task {task_id}", "instructions": "Do it."}

    def plan(*tasks: dict[str, str]) -> str:
        return json.dumps({"tasks": list(tasks), "reason": "Split by module."})

    assert check_port("output", "fix", schema, plan()) == {
        "tasks": [],
        "reason": "Split by module.",
    }
    assert isinstance(check_port("output", "fix", schema, plan(task("a"), task("b"))), dict)
    for bad in (
        plan(task("a"), task("b"), task("c")),  # over max_workers
        plan(task("Bad.Id")),  # not a slug, and a `.` would break the writer key
        plan({"id": "a", "title": "A"}),  # no instructions
    ):
        assert not isinstance(check_port("output", "fix", schema, bad), dict), bad


def test_an_orchestrator_may_replan_on_failure() -> None:
    """6.2: `replan` is optional, and off when unset."""
    node = OrchestratorNode.model_validate(
        orchestrator(agent("w"), replan={"on": "failure", "max_rounds": 2})
    )
    assert node.replan is not None and node.replan.max_rounds == 2
    assert OrchestratorNode.model_validate(orchestrator(agent("w"))).replan is None
    defaulted = OrchestratorNode.model_validate(orchestrator(agent("w"), replan={"on": "failure"}))
    assert defaulted.replan is not None and defaulted.replan.max_rounds == 1
    assert validate(orchestrator(agent("w"), replan={"on": "failure"})) == []


@pytest.mark.parametrize(
    "replan",
    [
        {"on": "failure", "max_rounds": 0},
        {"on": "failure", "max_rounds": MAX_REPLAN_ROUNDS + 1},
        {"on": "always"},
        {"max_rounds": 1},
    ],
    ids=["zero-rounds", "too-many-rounds", "unknown-trigger", "no-trigger"],
)
def test_replan_is_bounded(replan: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(workflow(orchestrator(agent("w"), replan=replan)))


def test_a_replan_schema_takes_fewer_tasks() -> None:
    node = OrchestratorNode.model_validate(orchestrator(agent("w")))
    schema = orchestrator_plan_schema(node, max_tasks=1)
    tasks = [{"id": t, "title": t, "instructions": "Do."} for t in ("a", "b")]
    one = json.dumps({"tasks": tasks[:1], "reason": "r"})
    assert isinstance(check_port("output", "fix", schema, one), dict)
    two = json.dumps({"tasks": tasks, "reason": "r"})
    assert not isinstance(check_port("output", "fix", schema, two), dict)
