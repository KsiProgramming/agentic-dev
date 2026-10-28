"""The "Audit codebase" template (4.6): read-only, it validates for every option, and a run
produces findings.json and a report whose path follows what was found."""

import itertools
import json
from typing import Any, get_args

import pytest
from pydantic import JsonValue, ValidationError

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    PUBLISH_TOOLS,
    READ_TOOLS,
    SCAN_TOOLS,
    AgentNode,
    GateNode,
    ParallelNode,
    ReduceNode,
    RouterNode,
    SequenceNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
    node_tools,
    validate_workflow,
    writer_node_ids,
)
from agentic_engine.templates import AuditParams, build_audit_spec, get_template
from agentic_engine.templates.audit import (
    MODELS,
    REVIEWS,
    SCANS,
    Check,
    ReportSeverity,
    at_least,
)
from agentic_runtime import AgentRequest, AgentRun, Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.findings import SEVERITIES
from agentic_runtime.testing import ScriptedToolExecutor

CHECKS: list[Check] = [*SCANS, *REVIEWS]


def _nodes(spec: WorkflowSpec) -> dict[str, Any]:
    return {node.id: node for _, node in iter_nodes(spec.root)}


def _issues(spec: WorkflowSpec) -> list[str]:
    raw = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    issues = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="claude-sonnet-5-5"
    )
    return [issue.message for issue in issues]


def test_the_audit_template_is_registered() -> None:
    template = get_template("audit-codebase")

    assert template is not None
    assert template.requires == ("claude", "github")
    schema = template.parameters_schema()
    assert list(schema["properties"]) == [
        "checks", "path", "min_severity", "reviewers", "reviewer_model", "report_model",
    ]  # fmt: skip
    assert schema["properties"]["checks"]["items"] == {"enum": CHECKS, "type": "string"}
    assert "$defs" not in schema
    assert set(get_args(ReportSeverity)) == set(SEVERITIES)
    assert schema["properties"]["reviewers"] == {
        "default": 1,
        "description": schema["properties"]["reviewers"]["description"],
        "maximum": 3,
        "minimum": 1,
        "title": "Reviewers",
        "type": "integer",
    }
    model = schema["properties"]["report_model"]["anyOf"][0]
    assert model == {"enum": list(MODELS), "type": "string"}


def test_default_options_build_the_audit_flow() -> None:
    spec = build_audit_spec(AuditParams())
    nodes = _nodes(spec)

    assert isinstance(spec.root, SequenceNode)
    assert [s.id for s in spec.root.steps] == ["checks", "merge", "report_path"]
    checks = nodes["checks"]
    assert isinstance(checks, ParallelNode)
    assert [b.id for b in checks.branches] == CHECKS
    assert nodes["lint"] == ToolNode(
        type="tool", id="lint", tool="scan.lint", args={"path": ".", "linters": "auto"}
    )
    assert nodes["secrets"].args == {"path": "."}
    review = nodes["security"]
    assert isinstance(review, AgentNode)
    assert set(review.tools) == {"repo.list_files", "repo.read_file", "repo.search"}
    assert review.output_schema is not None and review.model is None
    assert '`category` "security"' in review.instructions
    merge = nodes["merge"]
    assert isinstance(merge, ReduceNode)
    assert (merge.strategy, merge.writes) == ("dedupe", "findings.json")
    router = nodes["report_path"]
    assert isinstance(router, RouterNode)
    assert router.route_ids == ["clean", "fix_first", "default"]
    assert [r.when for r in router.routes] == [
        '!artifacts["findings.json"].findings.exists(f, f.severity in '
        '["critical", "high", "medium", "low"])',
        'artifacts["findings.json"].findings.exists(f, f.severity in ["critical", "high"])',
    ]
    for report in ("clean_report", "fix_first_report", "standard_report"):
        assert (nodes[report].reads, nodes[report].writes) == (["findings.json"], "report.md")
    assert _issues(spec) == []


def test_the_audit_is_read_only() -> None:
    """Mission principle 3: no gate is needed because nothing irreversible runs; no agent can
    write, and nothing publishes."""
    for params in (AuditParams(), AuditParams(reviewers=3)):
        spec = build_audit_spec(params)
        tools = {tool for _, node in iter_nodes(spec.root) for tool in node_tools(node)}

        assert tools <= READ_TOOLS | SCAN_TOOLS
        assert not tools & PUBLISH_TOOLS
        assert not any(t.startswith("github.") for t in tools)
        assert writer_node_ids(spec.root) == set()
        assert not any(isinstance(node, GateNode) for _, node in iter_nodes(spec.root))


@pytest.mark.parametrize("reviewers", [1, 2, 3])
def test_every_set_of_checks_validates(reviewers: int) -> None:
    for size in range(1, len(CHECKS) + 1):
        for checks in itertools.combinations(CHECKS, size):
            spec = build_audit_spec(AuditParams(checks=list(checks), reviewers=reviewers))

            assert _issues(spec) == [], checks
            writes = {
                n.writes
                for _, n in iter_nodes(spec.root)
                if isinstance(n, AgentNode | ToolNode | ReduceNode) and n.writes
            }
            assert writes == {"findings.json", "report.md"}


@pytest.mark.parametrize("severity", ["info", "low", "medium", "high", "critical"])
def test_every_severity_validates_and_shapes_the_routes(severity: str) -> None:
    params = AuditParams.model_validate({"min_severity": severity})
    router = _nodes(build_audit_spec(params))["report_path"]

    listed = ", ".join(f'"{s}"' for s in at_least(params.min_severity))
    assert f"f.severity in [{listed}]" in (router.routes[0].when or "")
    assert f"severity is {', '.join(at_least(params.min_severity))}" in (
        router.default.instructions
    )
    assert _issues(build_audit_spec(params)) == []


def test_reviewers_vote_on_each_review_and_scanners_are_never_voted() -> None:
    nodes = _nodes(build_audit_spec(AuditParams(reviewers=3, reviewer_model="claude-opus-5-5")))

    security = nodes["security"]
    assert isinstance(security, SequenceNode)
    [reviewers, vote] = security.steps
    assert isinstance(reviewers, ParallelNode) and isinstance(vote, ReduceNode)
    assert [b.id for b in reviewers.branches] == ["security_1", "security_2", "security_3"]
    assert {b.model for b in reviewers.branches} == {"claude-opus-5-5"}  # type: ignore[union-attr]
    assert (vote.strategy, vote.from_, vote.min_votes, vote.writes) == (
        "vote", "security_reviewers", None, None,
    )  # fmt: skip
    assert isinstance(nodes["lint"], ToolNode)
    assert sum(isinstance(n, ReduceNode) and n.strategy == "vote" for n in nodes.values()) == 3


def test_one_check_writes_findings_without_a_merge() -> None:
    for check in CHECKS:
        for reviewers in (1, 2):
            spec = build_audit_spec(AuditParams(checks=[check], reviewers=reviewers))
            assert isinstance(spec.root, SequenceNode)

            first = spec.root.steps[0]
            assert first.id == check
            assert [s.id for s in spec.root.steps] == [check, "report_path"]
            assert _issues(spec) == []


def test_models_and_path_reach_the_spec() -> None:
    params = AuditParams(
        checks=["lint", "tests"], path="packages/api/", report_model="claude-haiku-5-5"
    )
    nodes = _nodes(build_audit_spec(params))

    assert params.path == "packages/api"
    assert nodes["lint"].args == {"path": "packages/api", "linters": "auto"}
    assert "Review `packages/api` for gaps in the tests" in nodes["tests"].instructions
    assert nodes["tests"].model is None
    assert {nodes[r].model for r in ("clean_report", "fix_first_report", "standard_report")} == {
        "claude-haiku-5-5"
    }


@pytest.mark.parametrize(
    "parameters",
    [
        {"checks": []},
        {"checks": ["lint", "lint"]},
        {"checks": ["style"]},
        {"path": "../outside"},
        {"path": "src/.git"},
        {"path": "/etc"},
        {"min_severity": "urgent"},
        {"reviewers": 0},
        {"reviewers": 4},
        {"reviewer_model": "gpt-5"},
        {"report_model": "claude-unpriced"},
        {"extra": True},
    ],
)
def test_bad_options_are_refused(parameters: dict[str, JsonValue]) -> None:
    template = get_template("audit-codebase")
    assert template is not None

    with pytest.raises(ValidationError):
        template.build_spec(parameters)


def _finding(fingerprint: str, severity: str, category: str = "lint") -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "tool": "agent" if category in REVIEWS else "ruff",
        "rule": "r",
        "severity": severity,
        "category": category,
        "path": "app.py",
        "line": 3,
        "message": "m",
    }


def _report(scanner: str, *findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "scanner": scanner,
        "checks": [{"path": ".", "kind": "repo", "tool": scanner, "status": "ran"}],
        "findings": list(findings),
        "counts": {},
        "truncated": False,
    }


class Reviewers:
    """Each review agent answers its findings report; a report writer writes a report."""

    def __init__(self, reviews: dict[str, dict[str, Any]]) -> None:
        self._reviews = reviews
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        review = self._reviews.get(request.node_id.split("_")[0])
        text = json.dumps(review) if review is not None else f"# Audit ({request.node_id})"
        return FakeRuntime({request.node_id: [Message(text=text), ECHO_USAGE]}).start(request)


def _tools(**reports: dict[str, Any]) -> ScriptedToolExecutor:
    return ScriptedToolExecutor(
        {
            f"scan.{name}": ToolOutput(text=json.dumps(report), data=report)
            for name, report in reports.items()
        }
    )


@pytest.mark.parametrize(
    ("lint", "security", "route"),
    [
        ([], [], "clean"),
        ([_finding("a", "low")], [_finding("b", "critical", "security")], "fix_first"),
        ([_finding("a", "medium")], [], "standard"),
        ([_finding("a", "info")], [], "clean"),
    ],
)
async def test_an_audit_run_writes_findings_and_takes_the_report_path(
    lint: list[dict[str, Any]], security: list[dict[str, Any]], route: str
) -> None:
    """Done when (4.6): an audit run branches on a condition and produces findings.json and a
    readable report."""
    spec = build_audit_spec(AuditParams(checks=["lint", "secrets", "security"]))
    runtime = Reviewers({"security": _report("agent", *security)})
    tools = _tools(lint=_report("lint", *lint), secrets=_report("secrets"))
    store, sink = InMemoryArtifactStore(), InMemoryEventSink()

    result = await run_workflow(spec, runtime, "", sink=sink, tools=tools, artifacts=store)

    assert result.status == "completed", {k: r.error for k, r in result.results.items()}
    report = f"{route}_report"
    assert [r.node_id for r in runtime.requests] == ["security", report]
    [chosen] = [e.payload for e in sink.events if e.type == "route_chosen"]
    assert chosen["route"] == ("default" if route == "standard" else route)
    findings = await store.get("findings.json")
    assert findings is not None
    merged = json.loads(findings.content)
    assert sorted(f["fingerprint"] for f in merged["findings"]) == sorted(
        f["fingerprint"] for f in [*lint, *security]
    )
    written = await store.get("report.md")
    assert written is not None and written.content == f"# Audit ({report})"
    assert runtime.requests[-1].input == findings.content
    assert sorted(c[0] for c in tools.calls) == ["scan.lint", "scan.secrets"]


async def test_three_reviewers_keep_only_what_most_of_them_found() -> None:
    spec = build_audit_spec(AuditParams(checks=["lint", "security"], reviewers=3))
    agreed, alone = _finding("agreed", "high", "security"), _finding("alone", "high", "security")
    answers = {
        "security_1": _report("agent", agreed, alone),
        "security_2": _report("agent", agreed),
        "security_3": _report("agent"),
    }

    class Three(Reviewers):
        def start(self, request: AgentRequest) -> AgentRun:
            self.requests.append(request)
            answer = answers.get(request.node_id)
            text = json.dumps(answer) if answer is not None else "# Audit"
            return FakeRuntime({request.node_id: [Message(text=text), ECHO_USAGE]}).start(request)

    runtime = Three({})
    store = InMemoryArtifactStore()

    result = await run_workflow(
        spec, runtime, "", tools=_tools(lint=_report("lint")), artifacts=store
    )

    assert result.status == "completed", {k: r.error for k, r in result.results.items()}
    findings = await store.get("findings.json")
    assert findings is not None
    assert [f["fingerprint"] for f in json.loads(findings.content)["findings"]] == ["agreed"]
    assert runtime.requests[-1].node_id == "fix_first_report"
