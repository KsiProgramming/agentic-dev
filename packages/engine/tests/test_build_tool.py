"""`build.restore` (13.2): a tool node's, never an agent's. It opens a route out of the sandbox, so
validation refuses it everywhere else; a sequence with a tool node for it runs end to end and
writes the build report as an artifact."""

import json
from pathlib import Path
from typing import Any

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.graph import run_workflow
from agentic_engine.nodes import AGENT_TOOLS
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import (
    BUILD_TOOLS,
    PLATFORM_TOOLS,
    REPO_TOOL_PREFIXES,
    parse_spec,
    validate_workflow,
)
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

FIXTURES = Path(__file__).parent / "fixtures" / "specs"

REPORT: dict[str, Any] = {
    "tool": "build.restore",
    "checks": [
        {
            "path": "web",
            "ecosystem": "node",
            "manager": "pnpm",
            "lockfile": "pnpm-lock.yaml",
            "status": "ran",
            "packages": 42,
        }
    ],
    "counts": {"ran": 1, "skipped": 0, "failed": 0},
    "truncated": False,
}


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def issues(raw: dict[str, Any]) -> list[tuple[str, str]]:
    found = validate_workflow(
        raw,
        policy=PLATFORM_POLICY,
        priced=frozenset({"default"}).__contains__,
        default_model="default",
    )
    return [(i.code, i.path) for i in found]


def test_build_restore_is_a_platform_tool_that_needs_a_repo_and_no_agent_may_have() -> None:
    assert {"build.restore", "build.test"} == BUILD_TOOLS
    assert BUILD_TOOLS <= PLATFORM_TOOLS
    assert "build." in REPO_TOOL_PREFIXES
    assert not BUILD_TOOLS & set(AGENT_TOOLS)


def test_a_tool_node_may_call_it() -> None:
    assert issues(load("valid/build-restore.json")) == []


def test_an_agent_may_not() -> None:
    assert issues(load("invalid/build-restore-by-agent.json")) == [
        ("tool_node_only", "root.steps[0]")
    ]


def test_an_orchestrators_hub_may_not() -> None:
    raw = load("valid/orchestrator-docs.json")
    hub = next(n for n in _walk(raw["root"]) if n.get("type") == "orchestrator")["hub"]
    hub["tools"] = ["repo.list_files", "build.restore"]

    [(code, _)] = issues(raw)

    assert code == "schema"  # a hub may only read the repo


def test_an_agent_in_an_orchestrators_body_may_not() -> None:
    raw = load("valid/orchestrator-docs.json")
    body = next(n for n in _walk(raw["root"]) if n.get("type") == "orchestrator")["body"]
    agent = next(n for n in _walk(body) if n.get("type") == "agent")
    agent["tools"] = [*agent.get("tools", []), "build.restore"]

    assert [code for code, _ in issues(raw)] == ["tool_node_only"]


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for key in ("steps", "branches"):
        for child in node.get(key, []):
            found += _walk(child)
    for key in ("body", "call", "default"):
        if isinstance(node.get(key), dict):
            found += _walk(node[key])
    return found


async def test_a_build_tool_node_writes_the_report_and_the_next_step_reads_it() -> None:
    spec = parse_spec(load("valid/build-restore.json"))
    tools = ScriptedToolExecutor(
        {"build.restore": ToolOutput(text=json.dumps(REPORT), data=REPORT)}
    )
    runtime = FakeRuntime({"summariser": [Message(text="It builds."), ECHO_USAGE]})
    store = InMemoryArtifactStore()

    result = await run_workflow(spec, runtime, "", tools=tools, artifacts=store)

    assert result.status == "completed"
    assert tools.calls == [("build.restore", {"path": ".", "ecosystems": "auto"})]
    stored = await store.get("build.json")
    assert stored is not None
    assert json.loads(stored.content) == REPORT
    assert json.loads(runtime.requests[-1].input) == REPORT  # what the summariser receives
