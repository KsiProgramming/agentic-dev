"""The audit's "fix selected findings" steps (6.7): a selection gate on findings.json, an
orchestrator whose fixers fix the chosen findings, a gate on the diff and one pull request. On
the fake runtime with a fake integrator; the tests check what every agent receives (lessons rule
1), not only the run's outcome."""

import json
from typing import Any
from uuid import uuid4

from pydantic import JsonValue

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import WorkflowRunResult, resume_workflow, run_workflow
from agentic_engine.spec import (
    PUBLISH_TOOLS,
    READ_TOOLS,
    SCAN_TOOLS,
    WRITE_TOOLS,
    GateNode,
    OrchestratorNode,
    ToolNode,
    WorkflowSpec,
    iter_nodes,
    node_tools,
)
from agentic_engine.templates import AuditParams, build_audit_spec
from agentic_runtime import AgentRequest, AgentRun, Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, Script
from agentic_runtime.testing import ScriptedToolExecutor

from .test_gate import saver
from .test_orchestrator_integrate import Merger

PULL: dict[str, JsonValue] = {
    "url": "https://github.com/acme/hello/pull/9",
    "number": 9,
    "head": "agent/run/fix",
    "base": "main",
    "commit": "b" * 40,
}


def finding(key: str, severity: str, path: str, category: str = "security") -> dict[str, Any]:
    return {
        "fingerprint": key,
        "tool": "agent" if category == "security" else "ruff",
        "rule": f"rule-{key}",
        "severity": severity,
        "category": category,
        "path": path,
        "line": 3,
        "message": f"Issue {key}.",
    }


def report(scanner: str, *findings: dict[str, Any]) -> dict[str, Any]:
    return {
        "scanner": scanner,
        "checks": [{"path": ".", "kind": "repo", "tool": scanner, "status": "ran"}],
        "findings": list(findings),
        "counts": {},
        "truncated": False,
    }


LINT = report("lint", finding("a", "low", "util.py", "lint"))
SECURITY = report("agent", finding("b", "critical", "db.py"), finding("c", "high", "auth.py"))
PLAN = json.dumps(
    {
        "tasks": [
            {"id": "db", "title": "Fix db.py", "instructions": "Fix b at db.py:3."},
            {"id": "util", "title": "Fix util.py", "instructions": "Fix a at util.py:3."},
        ],
        "reason": "One task per file.",
    }
)


class AuditTeam:
    """The audit's agents: the reviewer answers its report, report writers a title, the lead
    `PLAN`, and each fixer a summary of its task."""

    def __init__(self, tools: ScriptedToolExecutor) -> None:
        self.requests: list[AgentRequest] = []
        self.tools = tools

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        node = request.node_id
        if node == "security":
            text = json.dumps(SECURITY)
        elif node == "fix":
            text = PLAN
        elif node.startswith("fix."):
            # A fixed order of events: db's fixer ends before util's.
            delay = Delay(0.05 if node == "fix.db" else 0.15)
            path = f"{node.removeprefix('fix.')}.py"
            script: Script = [delay, CallTool("repo.write_file", {"path": path})]
            script += [Message(text=f"### {node}\n- fixed"), ECHO_USAGE]
            return FakeRuntime({node: script}, tools=self.tools).start(request)
        else:
            text = f"# Audit ({node})"
        return FakeRuntime({node: [Message(text=text), ECHO_USAGE]}).start(request)

    def of(self, node_id: str) -> list[AgentRequest]:
        return [r for r in self.requests if r.node_id == node_id]


class AuditRun:
    """One audit run with `fix` on, across its pauses."""

    def __init__(self) -> None:
        self.spec: WorkflowSpec = build_audit_spec(
            AuditParams(checks=["lint", "security"], fix=True)
        )
        self.tools = ScriptedToolExecutor(
            {
                "scan.lint": ToolOutput(text=json.dumps(LINT), data=LINT),
                "repo.write_file": "wrote",
                "github.openPR": ToolOutput(text="opened #9", data=PULL),
            }
        )
        self.team = AuditTeam(self.tools)
        self.merger = Merger()
        self.sink = InMemoryEventSink()
        self.checkpointer = saver()
        self.artifacts = InMemoryArtifactStore()
        self.run_id = uuid4()
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec,
            self.team,
            "",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            tools=self.tools,
            artifacts=self.artifacts,
            integrator=self.merger,
        )

    async def decide(self, decision: GateDecision) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.team,
            "",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            tools=self.tools,
            decision=decision,
            artifacts=self.artifacts,
            integrator=self.merger,
        )

    def last(self, kind: str) -> RunEvent:
        return next(e for e in reversed(self.sink.events) if e.type == kind)


def test_with_fix_off_the_audit_is_unchanged_and_read_only() -> None:
    plain = build_audit_spec(AuditParams())
    assert [s.id for s in plain.root.steps] == ["checks", "merge", "report_path"]  # type: ignore[attr-defined]
    assert plain == build_audit_spec(AuditParams(fix=False))
    assert "Read-only" in (plain.description or "")


def test_with_fix_on_only_the_fixers_write_and_the_publish_is_gated() -> None:
    spec = build_audit_spec(AuditParams(fix=True, fixer_model="claude-sonnet-5-5"))
    nodes = {node.id: node for _, node in iter_nodes(spec.root)}

    assert [s.id for s in spec.root.steps][-4:] == [  # type: ignore[attr-defined]
        "select_fixes",
        "fix",
        "approve_pr",
        "publish",
    ]
    select = nodes["select_fixes"]
    assert isinstance(select, GateNode) and select.select is not None
    assert (select.select.artifact, select.select.key, select.on_reject) == (
        "findings.json",
        "fingerprint",
        "end",
    )
    fix = nodes["fix"]
    assert isinstance(fix, OrchestratorNode)
    assert set(fix.hub.tools) <= READ_TOOLS  # lessons rule 4: the lead reads the code
    assert fix.hub.model == "claude-sonnet-5-5" and fix.replan is not None
    writing = {n.id for _, n in iter_nodes(spec.root) if set(node_tools(n)) & WRITE_TOOLS}
    assert writing == {"fixer"}
    publishing = [n.id for _, n in iter_nodes(spec.root) if set(node_tools(n)) & PUBLISH_TOOLS]
    assert publishing == ["publish"]
    publish = nodes["publish"]
    assert isinstance(publish, ToolNode) and publish.args["from_node"] == "fix"
    others = {t for i, n in nodes.items() if i not in ("fixer", "publish") for t in node_tools(n)}
    assert others <= READ_TOOLS | SCAN_TOOLS
    assert "pull request" in (spec.description or "")


async def test_the_selected_findings_become_one_pull_request() -> None:
    """Done when (6.7): selected findings become a fix PR. Only the chosen findings reach the
    lead, each fixer works on its task's branch, the PR gate shows the integration branch, and
    the PR's body says what the fixers did."""
    run = AuditRun()

    paused = await run.start()
    assert paused.status == "waiting" and paused.waiting_at == "select_fixes"
    shown = run.last("gate_waiting").payload["select"]
    assert isinstance(shown, dict)
    assert shown["keys"] == ["b", "c", "a"]  # findings.json, most severe first
    assert shown["preselected"] == ["b", "c"]

    paused = await run.decide(GateDecision(decision="approve", selection=["b", "a"]))
    assert paused.status == "waiting" and paused.waiting_at == "approve_pr"

    # The lead gets exactly the chosen findings, as data, and only read tools.
    (hub,) = run.team.of("fix")
    chosen = json.loads(hub.input)
    assert [f["fingerprint"] for f in chosen["findings"]] == ["b", "a"]
    assert chosen["counts"]["critical"] == 1 and chosen["counts"]["high"] == 0
    assert set(hub.tools) <= READ_TOOLS
    selected = await run.artifacts.get("selected-findings.json")
    assert selected is not None and json.loads(selected.content) == chosen
    # Each fixer gets its task and the chosen findings, writes on its task's branch.
    fixers = [r for r in run.team.requests if r.node_id.startswith("fix.")]
    assert sorted(r.node_id for r in fixers) == ["fix.db", "fix.util"]
    for request in fixers:
        given = json.loads(request.input)
        assert json.loads(given["input"]) == chosen  # the orchestrator's input, as text
        assert given["task"]["id"] == request.node_id.removeprefix("fix.")
        assert {"repo.write_file", "repo.commit"} <= set(request.tools)
    assert run.merger.merged == ["fix.db", "fix.util"]
    # The PR gate shows the integration branch as the one writer.
    waiting = run.last("gate_waiting").payload
    assert waiting["title"] == "Open a pull request with the fixes?"
    assert "select" not in waiting
    fixes = await run.artifacts.get("fixes.md")
    assert fixes is not None and "### fix.db" in fixes.content

    done = await run.decide(GateDecision(decision="approve"))

    assert done.status == "completed", {k: r.error for k, r in done.results.items()}
    (call,) = [args for name, args in run.tools.calls if name == "github.openPR"]
    assert call["from_node"] == "fix"
    body = call["body"]
    assert isinstance(body, str) and body.endswith(fixes.content[:60_000])
    assert "body_from" not in call
    assert run.last("pr_opened").payload == PULL


async def test_rejecting_the_selection_ends_the_audit_completed_with_no_fix() -> None:
    run = AuditRun()
    await run.start()

    done = await run.decide(GateDecision(decision="reject"))

    assert done.status == "completed"
    assert run.team.of("fix") == []
    assert not [r for r in run.team.requests if r.node_id.startswith("fix.")]
    assert [name for name, _ in run.tools.calls] == ["scan.lint"]  # nothing written
    assert await run.artifacts.get("report.md") is not None
