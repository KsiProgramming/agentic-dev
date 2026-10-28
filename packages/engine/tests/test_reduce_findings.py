"""Roadmap 4.5, "duplicate findings are merged with severity and confidence": `dedupe` and `vote`
reduces merge the findings reports of a parallel's branches or a map's items, with no model."""

import json
from pathlib import Path
from typing import Any

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import run_workflow
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import ValidationIssue, WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURE = Path(__file__).parent / "fixtures" / "specs" / "valid" / "findings-merge.json"


def _finding(fingerprint: str | None, severity: str = "low", **fields: Any) -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "tool": "ruff",
        "rule": "F401",
        "severity": severity,
        "category": "lint",
        "path": "app.py",
        "line": 3,
        "message": "unused import",
        **fields,
    }


def _report(scanner: str, *findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "scanner": scanner,
        "checks": [{"path": ".", "kind": "repo", "tool": scanner, "status": "ran"}],
        "findings": list(findings),
        "counts": {"low": len(findings)},
        "truncated": False,
    }


LINT = _report("lint", _finding("unused"), _finding("only-lint", line=9))
SECRETS = _report("secrets", _finding("key", "high", category="secret", tool="gitleaks"))
REVIEW = _report(
    "lint",
    _finding("unused", "medium", tool="agent", confidence=0.5),
    _finding("key", "high", category="secret", tool="agent"),
)


def _spec(**reduce: Any) -> WorkflowSpec:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["root"]["steps"][1].update(reduce)
    return parse_spec(raw)


def _tools() -> ScriptedToolExecutor:
    return ScriptedToolExecutor(
        {
            "scan.lint": ToolOutput(text=json.dumps(LINT), data=LINT),
            "scan.secrets": ToolOutput(text=json.dumps(SECRETS), data=SECRETS),
        }
    )


def _runtime(review: dict[str, Any] = REVIEW) -> FakeRuntime:
    return FakeRuntime(
        {
            "reviewer": [Message(text=json.dumps(review)), ECHO_USAGE],
            "summary": [Message(text="Two issues."), ECHO_USAGE],
        }
    )


def _of(events: list[RunEvent], type: str, node_id: str) -> list[RunEvent]:
    return [e for e in events if e.type == type and e.node_id == node_id]


async def test_dedupe_merges_duplicates_with_severity_and_confidence() -> None:
    runtime, store, sink = _runtime(), InMemoryArtifactStore(), InMemoryEventSink()

    result = await run_workflow(_spec(), runtime, "", tools=_tools(), artifacts=store, sink=sink)

    assert result.status == "completed"
    stored = await store.get("findings.json")
    assert stored is not None
    report = json.loads(stored.content)
    assert report["scanner"] == "merged"
    by_fp = {f["fingerprint"]: f for f in report["findings"]}
    assert set(by_fp) == {"unused", "only-lint", "key"}
    assert (by_fp["unused"]["severity"], by_fp["unused"]["sources"]) == (
        "medium",
        ["lint", "reviewer"],
    )
    assert by_fp["unused"]["confidence"] == round(2 / 3 * 0.75, 2)
    assert by_fp["key"]["sources"] == ["secrets", "reviewer"]
    assert by_fp["only-lint"]["confidence"] == 0.33
    assert [s["id"] for s in report["sources"]] == ["lint", "secrets", "reviewer"]
    (done,) = _of(sink.events, "node_completed", "merge")
    assert done.payload["merged"] == {"sources": 3, "findings_in": 5, "findings_out": 3}
    summary = runtime.requests[-1]
    assert json.loads(summary.input) == report


async def test_vote_keeps_only_what_enough_sources_reported() -> None:
    store = InMemoryArtifactStore()

    result = await run_workflow(
        _spec(strategy="vote", min_votes=2), _runtime(), "", tools=_tools(), artifacts=store
    )

    assert result.status == "completed"
    stored = await store.get("findings.json")
    assert stored is not None
    assert [f["fingerprint"] for f in json.loads(stored.content)["findings"]] == ["key", "unused"]


async def test_a_source_that_is_not_a_findings_report_fails_the_merge() -> None:
    sink = InMemoryEventSink()

    result = await run_workflow(
        _spec(),
        _runtime({"summary": "no findings here"}),
        "",
        tools=_tools(),
        artifacts=InMemoryArtifactStore(),
        sink=sink,
    )

    assert result.status == "failed"
    (failed,) = _of(sink.events, "node_failed", "merge")
    assert str(failed.payload["error"]).startswith("input of 'merge' (from 'reviewer') does not")
    port = failed.payload["port"]
    assert isinstance(port, dict) and port["from_node_id"] == "reviewer"


MAP_REPORTS = {
    "api": _report("lint", _finding("a")),
    "web": _report("lint", _finding("a"), _finding("b")),
}


def _map_spec(**reduce: Any) -> WorkflowSpec:
    body = {"type": "agent", "id": "review", "role": "R", "instructions": "Go."}
    return parse_spec(
        {
            "spec_version": "0",
            "id": "wf",
            "name": "Map then merge",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {
                        "type": "map",
                        "id": "each",
                        "over": '["api", "web"]',
                        "max_concurrency": 2,
                        "body": body,
                    },
                    {"type": "reduce", "id": "merge", "from": "each", **reduce},
                ],
            },
        }
    )


def _map_runtime() -> FakeRuntime:
    return FakeRuntime(
        default=lambda input: [Message(text=json.dumps(MAP_REPORTS[input])), ECHO_USAGE]
    )


async def test_dedupe_merges_a_maps_items() -> None:
    result = await run_workflow(_map_spec(strategy="dedupe"), _map_runtime(), "")

    assert result.status == "completed"
    merged = result.results["merge"].data
    assert merged is not None
    findings = merged["findings"]
    assert isinstance(findings, list)
    assert [(f["fingerprint"], f["sources"]) for f in findings if isinstance(f, dict)] == [
        ("a", ["0", "1"]),
        ("b", ["1"]),
    ]


async def test_a_vote_with_too_few_sources_fails() -> None:
    sink = InMemoryEventSink()

    result = await run_workflow(
        _map_spec(strategy="vote", min_votes=3), _map_runtime(), "", sink=sink
    )

    assert result.status == "failed"
    (failed,) = _of(sink.events, "node_failed", "merge")
    assert failed.payload["error"] == "vote 'merge' needs 3 sources, 2 completed"


async def test_concat_joins_a_parallels_branches_in_branch_order() -> None:
    spec = parse_spec(
        {
            "spec_version": "0",
            "id": "wf",
            "name": "Parallel then concat",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {
                        "type": "parallel",
                        "id": "both",
                        "join": "all",
                        "branches": [
                            {"type": "agent", "id": "a", "role": "R", "instructions": "Go."},
                            {"type": "agent", "id": "b", "role": "R", "instructions": "Go."},
                        ],
                    },
                    {"type": "reduce", "id": "join", "from": "both", "strategy": "concat"},
                ],
            },
        }
    )
    runtime = FakeRuntime(
        {"a": [Message(text="from a"), ECHO_USAGE], "b": [Message(text="from b"), ECHO_USAGE]}
    )

    result = await run_workflow(spec, runtime, "")

    assert result.status == "completed"
    assert result.results["join"].text == "from a\n\nfrom b"


def _validate(raw: object) -> list[ValidationIssue]:
    return validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=lambda _: True, default_model="default"
    )


def test_a_typed_reader_after_a_merge_is_checked_against_the_findings_schema() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["root"]["steps"][2]["input_schema"] = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }

    [issue] = _validate(raw)

    assert (issue.code, issue.path, issue.node_id) == ("port_mismatch", "root.steps[2]", "summary")
    assert "'merge'" in issue.message
