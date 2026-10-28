"""Run artifacts in the spec (4.3): a read needs a writer that always runs before it, writes do
not race, and a reader's typed input port follows the artifact to its writer."""

from typing import Any

from pydantic import TypeAdapter

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    ValidationIssue,
    artifact_issues,
    artifact_writers,
    port_edges,
    validate_workflow,
)
from agentic_engine.spec.models import AgentNode, Node

_node: TypeAdapter[Node] = TypeAdapter(Node)


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "R", "instructions": "Go.", **fields}


def sequence(*steps: dict[str, Any], node_id: str = "main") -> dict[str, Any]:
    return {"type": "sequence", "id": node_id, "steps": list(steps)}


def where(issues: list[ValidationIssue]) -> list[tuple[str, str, str | None]]:
    return [(i.code, i.path, i.node_id) for i in issues]


def issues(root: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    return where(artifact_issues(_node.validate_python(root)))


def validate(root: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    raw = {"spec_version": "0", "id": "wf", "name": "Workflow", "root": root}
    return where(
        validate_workflow(
            raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
        )
    )


def test_a_read_after_a_write_past_other_steps_and_a_gate_is_fine() -> None:
    root = sequence(
        agent("scan", writes="findings.json"),
        agent("summary"),
        {"type": "gate", "id": "approve", "title": "OK?"},
        agent("report", reads=["findings.json"]),
    )

    assert issues(root) == []
    writers = artifact_writers(_node.validate_python(root))
    assert {k: {n: w.id for n, w in v.items()} for k, v in writers.items()} == {
        "report": {"findings.json": "scan"}
    }


def test_a_read_with_no_earlier_writer_is_unknown_on_the_read() -> None:
    root = sequence(agent("report", reads=["a.json", "b.md"]), agent("w", writes="b.md"))

    assert issues(root) == [
        ("artifact_unknown", "root.steps[0].reads[0]", "report"),
        ("artifact_unknown", "root.steps[0].reads[1]", "report"),
    ]


def test_a_loop_body_cannot_read_what_it_writes_later_but_sees_what_it_wrote_before() -> None:
    later = {
        "type": "loop",
        "id": "revise",
        "until": "iteration >= 2",
        "max_iterations": 2,
        "body": sequence(
            agent("read", reads=["draft.md"]), agent("w", writes="draft.md"), node_id="b"
        ),
    }
    earlier = {
        **later,
        "body": sequence(
            agent("w", writes="draft.md"), agent("read", reads=["draft.md"]), node_id="b"
        ),
    }

    assert issues(later) == [("artifact_unknown", "root.body.steps[0].reads[0]", "read")]
    assert issues(earlier) == []


def test_after_a_parallel_its_branches_writes_are_visible_but_not_to_each_other() -> None:
    root = sequence(
        {
            "type": "parallel",
            "id": "review",
            "join": "all",
            "branches": [
                agent("security", writes="security.json"),
                agent("quality", reads=["security.json"]),
            ],
        },
        agent("report", reads=["security.json"]),
    )

    assert issues(root) == [("artifact_unknown", "root.steps[0].branches[1].reads[0]", "quality")]


def test_two_branches_writing_one_name_conflict_but_sequential_writers_do_not() -> None:
    racing = {
        "type": "parallel",
        "id": "review",
        "join": "any",
        "branches": [
            agent("a", writes="f.json"),
            sequence(agent("b", writes="f.json"), node_id="s"),
        ],
    }

    assert issues(racing) == [("artifact_conflict", "root.branches[1]", "b")]
    assert issues(sequence(agent("a", writes="f.json"), agent("b", writes="f.json"))) == []


def test_a_branch_may_overwrite_what_was_written_before_the_parallel() -> None:
    root = sequence(
        agent("first", writes="f.json"),
        {
            "type": "parallel",
            "id": "review",
            "join": "all",
            "branches": [agent("a", reads=["f.json"]), agent("b", writes="f.json")],
        },
    )

    assert issues(root) == []


def test_a_map_body_may_read_but_not_write() -> None:
    root = sequence(
        agent("plan", writes="plan.json"),
        {
            "type": "map",
            "id": "each",
            "over": "['a', 'b']",
            "max_concurrency": 2,
            "body": agent("worker", reads=["plan.json"], writes="out.json"),
        },
    )

    assert issues(root) == [("artifact_conflict", "root.steps[1].body", "worker")]


def test_a_reduce_can_write_for_a_later_reader() -> None:
    root = sequence(
        {
            "type": "map",
            "id": "each",
            "over": "['a', 'b']",
            "max_concurrency": 2,
            "body": agent("worker"),
        },
        {"type": "reduce", "id": "join", "from": "each", "strategy": "concat", "writes": "all.md"},
        agent("report", reads=["all.md"]),
    )

    assert validate(root) == []


def test_reads_must_be_unique() -> None:
    [(code, _path, node)] = validate(agent("a", reads=["f.json", "f.json"]))

    assert (code, node) == ("schema", "a")


OBJECT_WITH_FINDINGS = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array"}},
}


def test_a_reader_with_one_read_takes_its_port_from_the_writer() -> None:
    root = _node.validate_python(
        sequence(
            agent("scan", writes="findings.json", output_schema=OBJECT_WITH_FINDINGS),
            agent("summary"),
            agent("report", reads=["findings.json"], input_schema=OBJECT_WITH_FINDINGS),
        )
    )

    edges = [(p.id, c.id, path) for p, c, path in port_edges(root)]

    assert edges == [("scan", "summary", "root.steps[1]"), ("scan", "report", "root.steps[2]")]


def test_a_reader_with_several_reads_has_no_producer() -> None:
    root = _node.validate_python(
        sequence(
            agent("a", writes="a.json"),
            agent("b", writes="b.json"),
            agent("report", reads=["a.json", "b.json"]),
        )
    )

    assert [c.id for _, c, _ in port_edges(root)] == ["b"]


def test_port_mismatch_follows_the_artifact() -> None:
    wants_issues = {
        "type": "object",
        "required": ["issues"],
        "properties": {"issues": {"type": "array"}},
    }
    root = sequence(
        agent("scan", writes="findings.json", output_schema=OBJECT_WITH_FINDINGS),
        agent("summary", output_schema={"type": "object", "properties": {"issues": {}}}),
        agent("report", reads=["findings.json"], input_schema=wants_issues),
    )

    [issue] = validate_workflow(
        {"spec_version": "0", "id": "wf", "name": "Workflow", "root": root},
        policy=PLATFORM_POLICY,
        priced=lambda _: True,
        default_model="default",
    )

    assert (issue.code, issue.path, issue.node_id) == ("port_mismatch", "root.steps[2]", "report")
    assert "the output_schema of 'scan'" in issue.message


def test_writes_and_reads_are_optional_and_dumped_as_defaults() -> None:
    node = AgentNode.model_validate(agent("a"))

    assert (node.reads, node.writes) == ([], None)
