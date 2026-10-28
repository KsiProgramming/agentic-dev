"""Roadmap 4.4, "tool outputs feed specialist agents": the `scan-specialists` fixture runs three
scan tool nodes in parallel, each writing its findings report, and the `triage` agent's input is
exactly those reports."""

import json
from pathlib import Path
from typing import Any

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURE = Path(__file__).parent / "fixtures" / "specs" / "valid" / "scan-specialists.json"
TRIAGE = {"summary": "One leaked key.", "top": [{"fingerprint": "s1", "why": "A live key."}]}


def _report(scanner: str, *findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "scanner": scanner,
        "checks": [{"path": ".", "kind": "repo", "tool": scanner, "status": "ran"}],
        "findings": list(findings),
        "counts": {"high": len(findings)},
        "truncated": False,
    }


def _finding(fingerprint: str, severity: str = "high") -> dict[str, Any]:
    return {
        "fingerprint": fingerprint,
        "tool": "t",
        "rule": "r",
        "severity": severity,
        "path": "a.py",
        "message": "m",
    }


REPORTS = {
    "scan.lint": _report("lint", _finding("l1", "medium")),
    "scan.secrets": _report("secrets", _finding("s1")),
    "scan.dependencies": _report("dependencies"),
}


def _workflow() -> WorkflowSpec:
    return parse_spec(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _tools(reports: dict[str, Any]) -> ScriptedToolExecutor:
    return ScriptedToolExecutor(
        {name: ToolOutput(text=json.dumps(r), data=r) for name, r in reports.items()}
    )


def _of(events: list[RunEvent], type: str, node_id: str | None = None) -> list[RunEvent]:
    return [e for e in events if e.type == type and (node_id is None or e.node_id == node_id)]


async def test_scan_reports_feed_the_specialist_agent() -> None:
    runtime = FakeRuntime({"triage": [Message(text=json.dumps(TRIAGE)), ECHO_USAGE]})
    tools, store, sink = _tools(REPORTS), InMemoryArtifactStore(), InMemoryEventSink()

    result = await run_workflow(_workflow(), runtime, "", tools=tools, artifacts=store, sink=sink)

    assert result.status == "completed"
    assert sorted(name for name, _ in tools.calls) == sorted(REPORTS)
    assert {name: args for name, args in tools.calls}["scan.lint"] == {
        "linters": "auto",
        "path": ".",
    }
    written = {
        e.payload["name"]: e.payload["version"] for e in _of(sink.events, "artifact_written")
    }
    assert written == {
        "lint.json": 1,
        "secrets.json": 1,
        "dependencies.json": 1,
        "triage.json": 1,
    }
    (started,) = _of(sink.events, "node_started", "triage")
    assert started.payload["reads"] == [
        {"name": "lint.json", "version": 1},
        {"name": "secrets.json", "version": 1},
        {"name": "dependencies.json", "version": 1},
    ]
    (request,) = runtime.requests
    assert json.loads(request.input) == {
        "lint.json": REPORTS["scan.lint"],
        "secrets.json": REPORTS["scan.secrets"],
        "dependencies.json": REPORTS["scan.dependencies"],
    }
    stored = await store.get("triage.json")
    assert stored is not None and json.loads(stored.content) == TRIAGE


async def test_a_malformed_report_fails_at_its_edge() -> None:
    broken = {**REPORTS, "scan.secrets": {"scanner": "secrets", "findings": "none"}}
    runtime = FakeRuntime({"triage": [Message(text=json.dumps(TRIAGE)), ECHO_USAGE]})
    sink = InMemoryEventSink()

    result = await run_workflow(
        _workflow(), runtime, "", tools=_tools(broken), artifacts=InMemoryArtifactStore(), sink=sink
    )

    assert result.status == "failed"
    (failed,) = _of(sink.events, "node_failed", "secrets")
    assert str(failed.payload["error"]).startswith(
        "output of 'secrets' does not match its output_schema"
    )
    assert runtime.requests == []
