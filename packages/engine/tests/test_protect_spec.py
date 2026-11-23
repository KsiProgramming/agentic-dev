"""Protected paths and `start_from` in the workflow spec (13.5): each refusal has its code, path
and an actionable message."""

from typing import Any

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.protect import ANALYZER_CONFIG_GLOBS, PLATFORM_GLOBS, platform_rule
from agentic_engine.spec import ValidationIssue, validate_workflow

WRITE = ["repo.read_file", "repo.write_file", "repo.commit"]


def validate(raw: object) -> list[ValidationIssue]:
    return validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
    )


def agent(node_id: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": "agent",
        "id": node_id,
        "role": "R",
        "instructions": "Go.",
        "tools": WRITE,
        **fields,
    }


def gate(node_id: str = "gate") -> dict[str, Any]:
    return {"type": "gate", "id": node_id, "title": "Ok?", "prompt": "Approve."}


def publish(source: str) -> dict[str, Any]:
    return {
        "type": "tool",
        "id": "publish",
        "tool": "github.openPR",
        "args": {"from_node": source, "title": "T", "body": "B"},
    }


def workflow(*steps: dict[str, Any], **document: Any) -> dict[str, Any]:
    root = {"type": "sequence", "id": "main", "steps": list(steps)}
    return {"spec_version": "0", "id": "wf", "name": "W", "root": root, **document}


def codes(issues: list[ValidationIssue]) -> list[tuple[str, str]]:
    return [(i.code, i.path) for i in issues]


def test_the_platform_list_protects_ci_and_analyzer_config_at_any_depth() -> None:
    assert platform_rule(".github/workflows/ci.yml") == ".github/workflows/**"
    assert platform_rule("src/App/.editorconfig") == "**/.editorconfig"
    assert platform_rule("pkg/ruff.toml") == "**/ruff.toml"
    assert platform_rule("src/app.py") is None
    assert platform_rule("tests/test_cart.py") is None
    assert set(ANALYZER_CONFIG_GLOBS) < set(PLATFORM_GLOBS)
    assert ".github/workflows/**" not in ANALYZER_CONFIG_GLOBS


def test_a_workflow_with_protect_validates() -> None:
    spec = workflow(
        agent("writer"),
        gate(),
        publish("writer"),
        protect={"paths": ["tests/**"], "allow": {"writer": ["tests/**"]}},
    )
    assert validate(spec) == []


def test_a_malformed_glob_is_invalid_protect() -> None:
    spec = workflow(
        agent("writer"),
        protect={"paths": ["tests/**", " ", "../x", "/abs"], "allow": {"writer": ["[a]"]}},
    )
    issues = validate(spec)
    assert codes(issues) == [
        ("invalid_protect", "protect.paths[1]"),
        ("invalid_protect", "protect.paths[2]"),
        ("invalid_protect", "protect.paths[3]"),
        ("invalid_protect", "protect.allow.writer[0]"),
    ]
    assert "is empty" in issues[0].message
    assert "leaves the repo" in issues[1].message


def test_allow_names_a_writer() -> None:
    spec = workflow(
        {"type": "agent", "id": "reader", "role": "R", "instructions": "Go."},
        agent("writer"),
        protect={"allow": {"reader": ["tests/**"], "nobody": ["tests/**"]}},
    )
    assert codes(validate(spec)) == [
        ("allow_unknown_writer", "protect.allow.reader"),
        ("allow_unknown_writer", "protect.allow.nobody"),
    ]


def test_an_allowed_writer_needs_a_gate_before_a_publish() -> None:
    spec = workflow(agent("writer"), publish("writer"), protect={"allow": {"writer": ["tests/**"]}})
    issues = validate(spec)
    codes_ = {c for c, _ in codes(issues)}
    assert "protected_change_without_gate" in codes_
    message = next(i.message for i in issues if i.code == "protected_change_without_gate")
    assert "gate must follow 'writer'" not in message
    assert "a gate must follow it before 'publish'" in message


def test_an_allowed_writer_needs_a_gate_before_a_writer_starts_from_it() -> None:
    spec = workflow(
        agent("tests"),
        agent("impl", start_from="tests"),
        protect={"allow": {"tests": ["tests/**"]}},
    )
    assert ("protected_change_without_gate", "protect.allow.tests") in codes(validate(spec))


def test_start_from_with_a_gate_between_validates() -> None:
    assert validate(workflow(agent("tests"), gate(), agent("impl", start_from="tests"))) == []


def test_start_from_needs_a_gate() -> None:
    issues = validate(workflow(agent("tests"), agent("impl", start_from="tests")))
    assert codes(issues) == [("start_from_without_gate", "root.steps[1].start_from")]
    assert "a person approves" in issues[0].message


def test_start_from_must_name_a_writer_that_completes_before() -> None:
    reader = {"type": "agent", "id": "reader", "role": "R", "instructions": "Go."}
    cases = {
        "nobody": [agent("impl", start_from="nobody")],
        "reader": [reader, gate(), agent("impl", start_from="reader")],
        "impl": [agent("impl", start_from="impl")],
        "later": [agent("impl", start_from="later"), gate(), agent("later")],
    }
    for source, steps in cases.items():
        issues = validate(workflow(*steps))
        assert [c for c, _ in codes(issues)] == ["start_from_unknown_writer"], source


def test_start_from_is_not_allowed_on_a_node_that_does_not_write_or_in_a_map_or_parallel() -> None:
    reader = {"type": "agent", "id": "r", "role": "R", "instructions": "Go.", "start_from": "w"}
    issues = validate(workflow(agent("w"), gate(), reader))
    assert [c for c, _ in codes(issues)] == ["start_from_not_allowed"]
    parallel = {
        "type": "parallel",
        "id": "par",
        "branches": [agent("a", start_from="w"), agent("b")],
        "join": "all",
    }
    issues = validate(workflow(agent("w"), gate(), parallel))
    assert "start_from_not_allowed" in [c for c, _ in codes(issues)]


def test_an_orchestrator_may_start_from_a_writer() -> None:
    orchestrator = {
        "type": "orchestrator",
        "id": "team",
        "hub": {"role": "Lead", "instructions": "Plan.", "tools": ["repo.read_file"]},
        "body": agent("engineer"),
        "max_workers": 2,
        "max_concurrency": 1,
        "start_from": "tests",
    }
    assert validate(workflow(agent("tests"), gate(), orchestrator)) == []
    no_gate = validate(workflow(agent("tests"), orchestrator))
    assert [c for c, _ in codes(no_gate)] == ["start_from_without_gate"]


def test_a_worker_in_an_orchestrators_body_may_not_start_from() -> None:
    orchestrator = {
        "type": "orchestrator",
        "id": "team",
        "hub": {"role": "Lead", "instructions": "Plan.", "tools": ["repo.read_file"]},
        "body": agent("engineer", start_from="tests"),
        "max_workers": 2,
        "max_concurrency": 1,
    }
    issues = validate(workflow(agent("tests"), gate(), orchestrator))
    assert [c for c, _ in codes(issues)] == ["start_from_not_allowed"]
