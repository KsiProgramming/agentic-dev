"""The "Audit codebase" template (4.6) with the real scanners in the sandbox image and fake
agents: a repo with planted issues takes the `fix_first` report path, a clean one `clean`; both
store findings.json and report.md, the repo is not changed, and a planted secret never leaves the
sandbox. Needs Docker; the image is built from `packages/sandbox` if the daemon lacks it."""

import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import docker
import pytest
from docker.errors import DockerException

from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import WorkflowRunResult, run_workflow
from agentic_engine.templates import AuditParams, build_audit_spec
from agentic_runtime import AgentRequest, AgentRun, Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.findings import FindingsReport
from agentic_sandbox import RepoSource, Sandbox
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import ensure_sandbox_image, make_repo
from agentic_tools.scan import open_scan_tools

pytestmark = pytest.mark.integration

PLANTED = {
    "pyproject.toml": '[project]\nname = "app"\nversion = "0"\n\n[tool.ruff.lint]\nselect = ["F"]\n',
    "app.py": "import os\n\n\ndef f():\n    return undefined_name\n",
}
CLEAN = {
    "pyproject.toml": '[project]\nname = "app"\nversion = "0"\n\n[tool.ruff.lint]\nselect = ["F"]\n',
    "app.py": "def f() -> int:\n    return 1\n",
}


class Writers:
    """Fake agents: each report writer answers a Markdown report naming itself."""

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        report = f"# Audit\n\nWritten by {request.node_id}."
        return FakeRuntime({request.node_id: [Message(text=report), ECHO_USAGE]}).start(request)


@pytest.fixture
def docker_client() -> docker.DockerClient:
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    return client


async def _box(
    client: docker.DockerClient, root: Path, files: dict[str, str]
) -> AsyncIterator[Sandbox]:
    make_repo(root / "repo", files)
    manager = DockerSandboxManager(client, local_root=root)
    async with manager.open(uuid4(), RepoSource(url=str(root / "repo"))) as box:
        yield box


async def _audit(box: Sandbox) -> tuple[WorkflowRunResult, InMemoryArtifactStore, str, Writers]:
    spec = build_audit_spec(AuditParams(checks=["lint", "secrets", "dependencies"]))
    runtime, store, sink = Writers(), InMemoryArtifactStore(), InMemoryEventSink()
    head = await box.exec(["git", "rev-parse", "HEAD"])
    async with open_scan_tools(box) as tools:
        result = await run_workflow(spec, runtime, "", sink=sink, tools=tools, artifacts=store)
    assert (await box.exec(["git", "rev-parse", "HEAD"])).stdout == head.stdout
    assert (await box.exec(["git", "status", "--porcelain"])).stdout.strip() == ""
    events = json.dumps([e.model_dump(mode="json") for e in sink.events])
    return result, store, events, runtime


async def test_an_audit_with_planted_issues_reports_what_to_fix_first(
    docker_client: docker.DockerClient, tmp_path: Path
) -> None:
    secret = secrets.token_urlsafe(30)
    files = {**PLANTED, "settings.py": f'aws_secret_access_key = "{secret}"\n'}
    async for box in _box(docker_client, tmp_path, files):
        result, store, events, runtime = await _audit(box)

        assert result.status == "completed", {k: r.error for k, r in result.results.items()}
        assert [r.node_id for r in runtime.requests] == ["fix_first_report"]
        findings = await store.get("findings.json")
        assert findings is not None
        report = FindingsReport.model_validate_json(findings.content)
        assert report.scanner == "merged"
        assert {f.category for f in report.findings} >= {"lint", "secret"}
        assert {s.id for s in report.sources or []} == {"lint", "secrets", "dependencies"}
        written = await store.get("report.md")
        assert written is not None and "fix_first_report" in written.content
        assert secret not in findings.content
        assert secret not in events
        assert secret not in runtime.requests[0].input


async def test_a_clean_repo_gets_the_short_report(
    docker_client: docker.DockerClient, tmp_path: Path
) -> None:
    async for box in _box(docker_client, tmp_path, CLEAN):
        result, store, _, runtime = await _audit(box)

        assert result.status == "completed", {k: r.error for k, r in result.results.items()}
        findings = await store.get("findings.json")
        assert findings is not None
        assert FindingsReport.model_validate_json(findings.content).findings == []
        assert [r.node_id for r in runtime.requests] == ["clean_report"]
