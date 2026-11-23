"""Independent review (13.6): the `review` field of an agent and of a gate, and the validation
issues that say what to change."""

from typing import Any

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import validate_workflow
from agentic_runtime.findings import FindingsReport

WRITER: dict[str, Any] = {
    "type": "agent", "id": "writer", "role": "W", "instructions": "Go.",
    "tools": ["repo.write_file", "repo.commit"], "writes": "report.md",
}  # fmt: skip


def lens(lens_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "agent", "id": lens_id, "role": "Reviewer", "instructions": "Look.",
        "tools": ["repo.read_file", "repo.diff"], "review": {"spec_from": "spec.md"},
        **extra,
    }  # fmt: skip


def raw_spec() -> dict[str, Any]:
    """A loop whose body is a writer, three lenses, a dedupe and a gate with `review`."""
    body = [
        {"type": "tool", "id": "spec", "tool": "repo.list_files", "writes": "spec.md"},
        WRITER,
        {
            "type": "parallel", "id": "lenses", "join": "settled",
            "branches": [lens("correctness"), lens("security"), lens("performance")],
        },
        {"type": "reduce", "id": "merge", "from": "lenses", "strategy": "dedupe",
         "writes": "review.json"},
        {
            "type": "gate", "id": "approve", "title": "Right?",
            "review": {"from": "review.json", "block_at": "high", "max_rounds": 2,
                       "notes": "review-notes.md"},
        },
    ]  # fmt: skip
    return {
        "spec_version": "0",
        "id": "review",
        "name": "Review",
        "root": {
            "type": "sequence", "id": "main",
            "steps": [
                {
                    "type": "loop", "id": "build", "max_iterations": 3,
                    "until": 'results.approve.data.decision != "changes"',
                    "body": {"type": "sequence", "id": "round", "steps": body},
                },
                {"type": "tool", "id": "publish", "tool": "github.openPR",
                 "args": {"from_node": "writer", "title": "t", "notes_from": "review-notes.md"}},
            ],
        },
    }  # fmt: skip


def found(raw: dict[str, Any]) -> list[tuple[str, str]]:
    issues = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=frozenset({"default"}).__contains__,
        default_model="default",
    )  # fmt: skip
    return [(i.code, i.message) for i in issues]


def steps(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return raw["root"]["steps"][0]["body"]["steps"]


def lenses(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return steps(raw)[2]["branches"]


def codes(raw: dict[str, Any]) -> list[str]:
    return [c for c, _ in found(raw)]


def test_a_review_with_three_lenses_and_a_gate_has_no_issue() -> None:
    assert found(raw_spec()) == []


def test_the_findings_schema_has_the_lens_categories() -> None:
    category = FindingsReport.model_json_schema()["$defs"]["Category"]

    assert {"correctness", "performance", "compatibility", "accessibility"} <= set(category["enum"])


def test_a_review_agent_may_only_read_the_repo() -> None:
    raw = raw_spec()
    lenses(raw)[0]["tools"] = ["repo.read_file", "repo.write_file"]
    lenses(raw)[1]["tools"] = ["repo.read_file", "artifacts.read"]

    issues = found(raw)

    reviews = [m for c, m in issues if c == "invalid_review"]
    assert len(reviews) == 2
    assert "repo.write_file" in reviews[0]
    assert "artifacts.read" in reviews[1]


def test_a_review_agent_has_no_reads_or_ports() -> None:
    raw = raw_spec()
    lenses(raw)[0]["reads"] = ["spec.md"]
    lenses(raw)[1]["output_schema"] = {"type": "object"}
    lenses(raw)[2]["input_schema"] = {"type": "object"}

    issues = found(raw)

    reviews = [m for c, m in issues if c == "invalid_review"]
    assert len(reviews) == 3
    assert all("the engine builds its input" in m for m in reviews)


def test_a_review_agent_is_not_for_a_map_or_an_orchestrator() -> None:
    raw = raw_spec()
    body = steps(raw)
    body[2] = {
        "type": "map", "id": "each", "over": "results.spec.data", "max_concurrency": 2,
        "body": lens("security"),
    }  # fmt: skip
    body[3] = {"type": "reduce", "id": "merge", "from": "each", "strategy": "dedupe",
               "writes": "review.json"}  # fmt: skip

    issues = found(raw)

    assert "invalid_review" in [c for c, _ in issues]
    assert any("map or an orchestrator" in m for _, m in issues)


def test_review_of_must_be_a_writer_that_completes_before() -> None:
    ghost = raw_spec()
    lenses(ghost)[0]["review"]["of"] = "ghost"
    not_a_writer = raw_spec()
    lenses(not_a_writer)[0]["review"]["of"] = "spec"
    late = raw_spec()
    body = steps(late)
    body.insert(0, body.pop(1))  # the writer first: fine
    first = raw_spec()
    steps(first).append(steps(first).pop(1))  # the writer after the review: not before it

    assert codes(ghost) == ["review_unknown_writer"]
    assert "'ghost' is not a writer" in found(ghost)[0][1]
    assert codes(not_a_writer) == ["review_unknown_writer"]
    assert codes(late) == []
    assert "review_unknown_writer" in codes(first)


def test_without_of_a_writer_must_run_before_the_review() -> None:
    raw = raw_spec()
    steps(raw).append(steps(raw).pop(1))  # the writer now runs after the review

    issues = [m for c, m in found(raw) if c == "review_unknown_writer"]

    assert len(issues) == 3
    assert all("no writer runs before this node" in m for m in issues)


def test_a_gate_review_needs_a_loops_body() -> None:
    raw = raw_spec()
    loop = raw["root"]["steps"][0]
    raw["root"]["steps"][0] = {"type": "sequence", "id": "flat", "steps": loop["body"]["steps"]}

    assert "review_not_in_loop" in codes(raw)
    assert "in a loop's body" in dict(found(raw))["review_not_in_loop"]


def test_a_gate_review_reads_findings_written_before_it_in_the_body() -> None:
    missing = raw_spec()
    steps(missing)[-1]["review"]["from"] = "other.json"
    markdown = raw_spec()
    steps(markdown)[-1]["review"]["from"] = "report.md"
    untyped = raw_spec()
    steps(untyped)[1]["writes"] = "review.json"
    steps(untyped)[3]["writes"] = "merged.json"
    untyped_from = raw_spec()
    steps(untyped_from)[3] = {
        "type": "reduce", "id": "merge", "from": "lenses", "strategy": "concat",
        "writes": "review.json",
    }  # fmt: skip

    assert codes(missing) == ["invalid_gate_review"]
    assert "is not written before the gate" in found(missing)[0][1]
    assert codes(markdown) == ["invalid_gate_review"]
    assert "must be a .json artifact" in found(markdown)[0][1]
    assert "artifact_conflict" in codes(untyped) or "invalid_gate_review" in codes(untyped)
    assert codes(untyped_from) == ["invalid_gate_review"]
    assert "not typed as findings" in found(untyped_from)[0][1]


def test_a_review_cannot_share_a_gate_with_select_or_on_changes() -> None:
    raw = raw_spec()
    steps(raw)[-1]["on_changes"] = 1

    assert "schema" in codes(raw)


def test_spec_from_and_notes_from_must_be_written_before() -> None:
    raw = raw_spec()
    lenses(raw)[0]["review"]["spec_from"] = "nowhere.md"
    publish = raw["root"]["steps"][1]
    publish["args"]["notes_from"] = "nothing.md"

    issues = found(raw)

    assert [c for c, _ in issues] == ["artifact_unknown", "artifact_unknown"]
    assert "reviews against 'nowhere.md'" in issues[0][1]
    assert "takes its notes from 'nothing.md'" in issues[1][1]


def test_the_notes_artifact_is_written_by_the_gate_and_must_be_markdown() -> None:
    raw = raw_spec()
    steps(raw)[-1]["review"]["notes"] = "notes.json"

    assert "schema" in codes(raw)
