import asyncio
import base64
import io
import json
import logging
import re
import subprocess
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import docker
import pytest
from docker.errors import DockerException
from docker.models.containers import Container
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RunEvent
from agentic_engine.gate import FileEdit, GateDecision
from agentic_engine.graph import Checkpointer, checkpoint_serde
from agentic_engine.logging import JsonFormatter
from agentic_engine.policy import PolicyOverrides
from agentic_engine.spec import PUBLISH_TOOLS, READ_TOOLS, WRITE_TOOLS, WorkflowSpec, parse_spec
from agentic_engine.templates import DocsParams, build_docs_spec
from agentic_engine.templates.docs import PAGE_SEPARATOR
from agentic_runtime import (
    AgentRuntime,
    ClaudeRuntime,
    Completed,
    Failed,
    Message,
    ModelPrice,
    ToolExecutor,
    Usage,
)
from agentic_runtime.fake import ECHO_USAGE, CallTool, Delay, FakeRuntime, Script
from agentic_runtime.testing import MOCK_API_KEY, MockClaude, text_reply
from agentic_sandbox import FakeSandboxManager, RepoSource, Sandbox, SandboxManager
from agentic_sandbox.docker_backend import RUN_LABEL, DockerSandboxManager
from agentic_sandbox.testing import ensure_sandbox_image, make_repo
from agentic_secrets import LocalKeyProvider, generate_key_file, install_redaction
from agentic_store import (
    Workspace,
    active_seconds,
    create_run,
    enqueue_run,
    get_run,
    get_run_summary,
    list_run_events,
    put_connection,
    put_github_connection,
    record_approval,
    replace_policy_overrides,
    replace_price_overrides,
    request_cancel,
)
from agentic_tools.github import PUBLISH_TOOL_NAMES, GithubPublisher
from agentic_tools.repo import COMMIT_AUTHOR, READ_TOOL_NAMES, WRITE_TOOL_NAMES, open_repo_tools
from agentic_tools.testing import FakeGithub, bare_remote
from agentic_worker.main import RuntimeFactory, WorkerSettings, run

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
PROJECT = Path(__file__).resolve().parents[3]


def load_spec(name: str) -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / name).read_text(encoding="utf-8")))


def two_step_spec() -> WorkflowSpec:
    return load_spec("two-step-sequence.json")


@asynccontextmanager
async def worker(
    postgres_url: str,
    redis_url: str,
    *,
    runtime: AgentRuntime | None = None,
    make_runtime: RuntimeFactory | None = None,
    sandboxes: SandboxManager | None = None,
    checkpointer: Checkpointer | None = None,
    ready_file: Path | None = None,
    claude: MockClaude | None = None,
    master_key_file: Path | None = None,
    github: GithubPublisher | None = None,
    github_remote: Callable[[str], str] | None = None,
    **more_settings: Any,
) -> AsyncGenerator[asyncio.Event]:
    """A worker running in this event loop; yields its stop event and stops it on exit.

    With `claude`, runs use the Claude runtime with workspaces' stored keys (`master_key_file`),
    each on its own client from the mock. Its checkpoints are kept in memory (psycopg cannot run
    on the Windows test loop); pass one `checkpointer` to workers that must share them."""
    stop, ready = asyncio.Event(), asyncio.Event()
    checkpointer = checkpointer or InMemorySaver(serde=checkpoint_serde())
    settings = WorkerSettings(
        database_url=postgres_url,
        redis_url=redis_url,
        ready_file=ready_file,
        queue_poll_s=0.1,
        runtime="claude" if claude else "fake",
        master_key_file=master_key_file,
        **more_settings,
    )
    task = asyncio.create_task(
        run(
            settings,
            stop,
            ready,
            runtime=runtime,
            make_runtime=make_runtime,
            make_client=(lambda k: claude.make_client(k.get_secret_value())) if claude else None,
            sandboxes=sandboxes,
            checkpointer=checkpointer,
            github=github,
            github_remote=github_remote,
        )
    )
    try:
        async with asyncio.timeout(10):
            await ready.wait()
        yield stop
    finally:
        stop.set()
        async with asyncio.timeout(5):
            await task


async def wait_for_status(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, status: str
) -> None:
    # Generous: cloning this project into a container can take over 10 s on a loaded machine,
    # and a run cut off by a timeout is left for the next test's worker to reclaim.
    async with asyncio.timeout(30):
        while True:
            run = await get_run(sessions, run_id)
            if run is not None and run.status == status:
                return
            await asyncio.sleep(0.05)


async def wait_for_event(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, type: str, node_id: str
) -> None:
    async with asyncio.timeout(10):
        while True:
            events = await list_run_events(sessions, run_id)
            if any(e.type == type and e.node_id == node_id for e in events):
                return
            await asyncio.sleep(0.05)


async def submit(
    sessions: async_sessionmaker[AsyncSession],
    redis_url: str,
    spec: WorkflowSpec,
    repo: RepoSource | None = None,
) -> UUID:
    run_id = await create_run(sessions, spec, "go", repo)
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()
    return run_id


pytestmark = pytest.mark.integration


async def test_worker_starts_and_stops(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(`sessions` migrates the database: a worker reads `runs` as it starts.)"""
    ready_file = tmp_path / "worker-ready"
    caplog.set_level(logging.INFO, logger="agentic_worker")

    async with worker(postgres_url, redis_url, ready_file=ready_file):
        assert "worker ready" in caplog.messages
        assert ready_file.exists()

    assert caplog.messages[-1] == "worker stopping"
    assert not ready_file.exists()


async def test_worker_runs_a_queued_run(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with worker(postgres_url, redis_url):
        run_id = await submit(sessions, redis_url, two_step_spec())
        await wait_for_status(sessions, run_id, "completed")

    events = await list_run_events(sessions, run_id)
    assert events[0].type == "run_started"
    assert events[0].payload["input"] == "go"
    assert events[-1].type == "run_completed"


async def test_worker_carries_on_after_a_failed_or_unknown_run(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    runtime = FakeRuntime({"writer": [Failed(error="boom")]})
    async with worker(postgres_url, redis_url, runtime=runtime):
        await enqueue_run(redis, uuid4())
        failed = await submit(sessions, redis_url, two_step_spec())
        await wait_for_status(sessions, failed, "failed")
        completed = await submit(sessions, redis_url, load_spec("single-agent.json"))
        await wait_for_status(sessions, completed, "completed")
    await redis.aclose()

    assert (await list_run_events(sessions, failed))[-1].type == "run_failed"


async def test_a_stopped_worker_releases_its_run_and_the_next_resumes_it(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Stopping a worker is a drain (phase 1.3): its run is not ended, and the next worker
    resumes it after its last completed node."""
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    first = FakeRuntime({"reviewer": [Delay(30), ECHO_USAGE]})
    async with worker(postgres_url, redis_url, runtime=first, checkpointer=checkpointer):
        run_id = await submit(sessions, redis_url, two_step_spec())
        await wait_for_event(sessions, run_id, "node_started", "reviewer")

    run_after = await get_run(sessions, run_id)
    assert run_after is not None
    assert run_after.status == "running"
    assert (await list_run_events(sessions, run_id))[-1].type == "node_started"

    second = FakeRuntime()
    async with worker(postgres_url, redis_url, runtime=second, checkpointer=checkpointer):
        await wait_for_status(sessions, run_id, "completed")

    assert [r.node_id for r in second.requests] == ["reviewer"]
    events = await list_run_events(sessions, run_id)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    resumed = next(e for e in events if e.type == "run_resumed")
    assert resumed.payload == {"attempt": 2, "completed_nodes": ["writer"]}
    completed = [e.node_id for e in events if e.type == "node_completed"]
    assert completed == ["writer", "reviewer"]
    assert not [e for e in events if e.type in ("run_cancelled", "node_cancelled")]


async def test_a_one_node_run_on_claude_stores_text_and_usage(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    mock = MockClaude([text_reply("Five ", "lines.", input_tokens=30, output_tokens=7)])
    async with worker(postgres_url, redis_url, runtime=ClaudeRuntime(mock.client)):
        run_id = await submit(sessions, redis_url, load_spec("single-agent.json"))
        await wait_for_status(sessions, run_id, "completed")

    events = await list_run_events(sessions, run_id)
    agent = [(e.type, e.payload) for e in events if e.node_id == "summarizer"]
    assert [t for t, _ in agent] == [
        "node_started",
        "text_delta",
        "text_delta",
        "usage",
        "message",
        "completed",
        "node_completed",
    ]
    assert agent[3][1]["input_tokens"] == 30
    assert agent[4][1]["text"] == "Five lines."
    assert events[-1].type == "run_completed"
    assert "Read the README" in mock.requests[0]["system"]
    assert all(MOCK_API_KEY not in str(e.payload) for e in events)


def test_json_formatter_emits_one_json_object() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)

    entry = json.loads(JsonFormatter().format(record))

    assert entry["msg"] == "hello world"
    assert entry["level"] == "info"


def fake_with_tools(tools: ToolExecutor | None) -> AgentRuntime:
    return FakeRuntime(tools=tools)


async def test_a_run_with_a_repo_lists_its_files_in_a_sandbox(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    repos, boxes = tmp_path / "repos", tmp_path / "sandboxes"
    make_repo(repos / "hello")
    boxes.mkdir()
    sandboxes = FakeSandboxManager(local_root=repos, base_dir=boxes)
    repo = RepoSource(url=str(repos / "hello"))

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        run_id = await submit(sessions, redis_url, load_spec("list-repo-files.json"), repo)
        await wait_for_status(sessions, run_id, "completed")

    events = await list_run_events(sessions, run_id)
    call = next(e for e in events if e.type == "tool_call")
    result = next(e for e in events if e.type == "tool_result")
    assert (call.node_id, call.payload["name"]) == ("explorer", "repo.list_files")
    assert result.payload["is_error"] is False
    assert {"README.md", "src/", "src/app.py"} <= set(str(result.payload["output"]).splitlines())
    assert list(boxes.iterdir()) == []  # the sandbox is gone


class RecordingSandboxes:
    """Wraps a `SandboxManager`, noting in `order` when each sandbox is closed and setting
    `closed`. `inspect` runs in the sandbox just before it is closed, once the run has ended.
    Wait for `closed` before stopping the worker, or the teardown is cut short."""

    def __init__(
        self,
        inner: SandboxManager,
        order: list[str] | None = None,
        inspect: Callable[[Sandbox], Awaitable[None]] | None = None,
    ) -> None:
        self._inner, self._order, self._inspect = inner, order if order is not None else [], inspect
        self.closed = asyncio.Event()

    def keep(self, run_id: UUID) -> None:
        self._inner.keep(run_id)

    async def discard(self, run_id: UUID) -> None:
        await self._inner.discard(run_id)

    @asynccontextmanager
    async def open(
        self,
        run_id: UUID,
        repo: RepoSource,
        *,
        reuse: bool = False,
        git_env: Mapping[str, str] | None = None,
    ) -> AsyncGenerator[Sandbox]:
        try:
            async with self._inner.open(run_id, repo, reuse=reuse, git_env=git_env) as box:
                try:
                    yield box
                finally:
                    if self._inspect is not None:
                        await self._inspect(box)
        finally:
            self._order.append("sandbox closed")
            self.closed.set()


# Prints the writer branches, then each commit on them that the checkout's HEAD lacks, with its
# author, subject and files.
_BRANCH_LOG = """
git() { command git -c safe.directory="$(pwd -P)" "$@"; }
git branch --list 'agent/*' --format='%(refname:short)'
echo ---
git log --branches='agent/*' --not HEAD --format='%an <%ae>|%s' --name-only
"""


class BranchLog:
    """`inspect` for `RecordingSandboxes`: what the run left on `agent/*` branches."""

    def __init__(self) -> None:
        self.branches: list[str] = []
        self.commits: list[str] = []

    async def __call__(self, box: Sandbox) -> None:
        result = await box.exec(["sh", "-c", _BRANCH_LOG])
        branches, _, commits = result.stdout.partition("---\n")
        self.branches = branches.split()
        self.commits = [line for line in commits.splitlines() if line]


@pytest.mark.parametrize("fails", [False, True])
async def test_the_repo_tools_close_before_the_sandbox(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    order: list[str] = []
    sandboxes = RecordingSandboxes(FakeSandboxManager(local_root=repos), order)

    @asynccontextmanager
    async def recording_tools(sandbox: Sandbox, **options: Any) -> AsyncGenerator[ToolExecutor]:
        try:
            async with open_repo_tools(sandbox, **options) as tools:
                yield tools
        finally:
            order.append("tools closed")

    monkeypatch.setattr("agentic_worker.main.open_repo_tools", recording_tools)
    scripts = {"explorer": [Failed(error="boom")]} if fails else {}

    def make_runtime(tools: ToolExecutor | None) -> AgentRuntime:
        return FakeRuntime(scripts, tools=tools)

    async with worker(postgres_url, redis_url, make_runtime=make_runtime, sandboxes=sandboxes):
        repo = RepoSource(url=str(repos / "hello"))
        run_id = await submit(sessions, redis_url, load_spec("list-repo-files.json"), repo)
        await wait_for_status(sessions, run_id, "failed" if fails else "completed")

    assert order == ["tools closed", "sandbox closed"]


async def test_a_repo_that_cannot_be_cloned_fails_the_run_cleanly(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    repos = tmp_path / "repos"
    repos.mkdir()
    sandboxes = FakeSandboxManager(local_root=repos)
    repo = RepoSource(url=str(repos / "missing"))

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        failed = await submit(sessions, redis_url, load_spec("list-repo-files.json"), repo)
        await wait_for_status(sessions, failed, "failed")
        after = await submit(sessions, redis_url, load_spec("single-agent.json"))
        await wait_for_status(sessions, after, "completed")

    events = await list_run_events(sessions, failed)
    assert [e.type for e in events] == ["run_started", "run_failed"]
    error = str(events[-1].payload["error"])
    assert error.startswith("could not clone the repo")
    assert str(tmp_path) not in error
    assert tmp_path.as_posix() not in error


async def test_done_when_an_agent_lists_files_in_a_cloned_repo_inside_a_container(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    """Done when (1.1): an agent lists files in a cloned repo inside the container."""
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    sandboxes = DockerSandboxManager(client, local_root=repos)
    repo = RepoSource(url=str(repos / "hello"))

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        run_id = await submit(sessions, redis_url, load_spec("list-repo-files.json"), repo)
        await wait_for_status(sessions, run_id, "completed")

    events = await list_run_events(sessions, run_id)
    result = next(e for e in events if e.type == "tool_result")
    assert "src/pkg/__init__.py" in str(result.payload["output"]).splitlines()
    # The run ends before its sandbox is removed; give the removal a moment.
    async with asyncio.timeout(10):
        while True:
            if not containers_of(client, run_id):
                break
            await asyncio.sleep(0.1)


async def test_done_when_an_agent_answers_a_question_about_the_repo(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (1.2): an agent answers a question about the repo using the tools. The fake
    agent lists, reads and searches this project's own repo, cloned into a container, through the
    `repo` MCP server; the results hold the answer (the workspace members and their packages)."""
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    sandboxes = DockerSandboxManager(client, local_root=PROJECT)
    repo = RepoSource(url=str(PROJECT / ".git"))

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        run_id = await submit(sessions, redis_url, load_spec("ask-repo.json"), repo)
        await wait_for_status(sessions, run_id, "completed")

    events = await list_run_events(sessions, run_id)
    calls = [e.payload for e in events if e.type == "tool_call"]
    results = [e.payload for e in events if e.type == "tool_result"]
    assert [c["name"] for c in calls] == ["repo.list_files", "repo.read_file", "repo.search"]
    assert [r["is_error"] for r in results] == [False, False, False]
    listing, root_pyproject, hits = (str(r["output"]) for r in results)
    assert "packages/tools/" in listing.splitlines()
    assert 'members = ["packages/*"]' in root_pyproject
    assert "packages/tools/pyproject.toml:1: [project]" in hits.splitlines()
    assert events[-1].type == "run_completed"
    async with asyncio.timeout(10):
        while True:
            if not containers_of(client, run_id):
                break
            await asyncio.sleep(0.1)


def containers_of(client: docker.DockerClient, run_id: UUID) -> list[Container]:
    """The run's sandbox containers. Sparse: a full listing inspects each container, which fails
    if one is removed in between, as these tests' polls race the sandbox's removal."""
    return client.containers.list(all=True, sparse=True, filters={"label": f"{RUN_LABEL}={run_id}"})


def assert_wrote_and_committed_notes(events: list[RunEvent], run_id: UUID) -> None:
    """The `write-file.json` run on the unscripted fake agent: it read the README, wrote and
    committed NOTES.md on its branch, and the tool node then listed the shared checkout."""
    calls = [(e.node_id, e.payload["name"]) for e in events if e.type == "tool_call"]
    outputs = [
        (str(e.payload["output"]), e.payload["is_error"]) for e in events if e.type == "tool_result"
    ]
    assert calls == [
        ("writer", "repo.read_file"),
        ("writer", "repo.write_file"),
        ("writer", "repo.commit"),
        ("list", "repo.list_files"),
    ]
    assert [is_error for _, is_error in outputs[1:]] == [False, False, False]
    assert outputs[1][0].startswith("wrote NOTES.md (")
    assert re.fullmatch(rf"[0-9a-f]{{7,}} on agent/{run_id}/writer: NOTES\.md", outputs[2][0])
    assert "NOTES.md" not in outputs[3][0].splitlines()  # the shared checkout is untouched
    assert events[-1].type == "run_completed"


async def test_a_writer_commits_a_file_to_its_branch(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    branch_log = BranchLog()
    sandboxes = RecordingSandboxes(FakeSandboxManager(local_root=repos), inspect=branch_log)

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        repo = RepoSource(url=str(repos / "hello"))
        run_id = await submit(sessions, redis_url, load_spec("write-file.json"), repo)
        await wait_for_status(sessions, run_id, "completed")
        await asyncio.wait_for(sandboxes.closed.wait(), 10)

    assert_wrote_and_committed_notes(await list_run_events(sessions, run_id), run_id)
    name, email = COMMIT_AUTHOR
    assert branch_log.branches == [f"agent/{run_id}/writer"]
    assert branch_log.commits == [f"{name} <{email}>|Add NOTES.md", "NOTES.md"]


async def test_done_when_an_agent_commits_a_file_to_its_branch(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (1.6): an agent commits a file to `agent/<run>/<node>`. The fake agent writes
    NOTES.md in its worktree of this project's repo, inside a container, and commits it with
    `repo.commit`; before the sandbox goes, git there shows one commit by the platform on the
    branch, touching only that file."""
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    branch_log = BranchLog()
    sandboxes = RecordingSandboxes(
        DockerSandboxManager(client, local_root=PROJECT), inspect=branch_log
    )
    repo = RepoSource(url=str(PROJECT / ".git"))

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        run_id = await submit(sessions, redis_url, load_spec("write-file.json"), repo)
        await wait_for_status(sessions, run_id, "completed")
        await asyncio.wait_for(sandboxes.closed.wait(), 30)

    assert_wrote_and_committed_notes(await list_run_events(sessions, run_id), run_id)
    name, email = COMMIT_AUTHOR
    assert branch_log.branches == [f"agent/{run_id}/writer"]
    assert branch_log.commits == [f"{name} <{email}>|Add NOTES.md", "NOTES.md"]
    async with asyncio.timeout(10):
        while True:
            if not containers_of(client, run_id):
                break
            await asyncio.sleep(0.1)


@pytest.fixture
def master_key(tmp_path: Path) -> Path:
    path = tmp_path / "master.key"
    generate_key_file(path)
    return path


async def new_workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def submit_to(
    sessions: async_sessionmaker[AsyncSession], redis_url: str, workspace_id: UUID
) -> UUID:
    run_id = await create_run(
        sessions, load_spec("single-agent.json"), "go", workspace_id=workspace_id
    )
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()
    return run_id


async def test_each_run_uses_its_workspace_s_stored_claude_key(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, master_key: Path
) -> None:
    keys = LocalKeyProvider.from_file(master_key)
    first, second = await new_workspace(sessions), await new_workspace(sessions)
    await put_connection(sessions, keys, first, "claude", SecretStr("sk-ant-first-workspace"))
    await put_connection(sessions, keys, second, "claude", SecretStr("sk-ant-second-workspace"))
    mock = MockClaude([text_reply("one"), text_reply("two")])

    async with worker(postgres_url, redis_url, claude=mock, master_key_file=master_key):
        run_a = await submit_to(sessions, redis_url, first)
        await wait_for_status(sessions, run_a, "completed")
        run_b = await submit_to(sessions, redis_url, second)
        await wait_for_status(sessions, run_b, "completed")

    assert mock.api_keys == ["sk-ant-first-workspace", "sk-ant-second-workspace"]
    # One client per run (after the mock's own), each closed when its run ended.
    assert len(mock.clients) == 3
    assert all(c.is_closed() for c in mock.clients[1:])


async def test_usage_is_priced_with_the_workspace_s_prices(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, master_key: Path
) -> None:
    keys = LocalKeyProvider.from_file(master_key)
    workspace = await new_workspace(sessions)
    await put_connection(sessions, keys, workspace, "claude", SecretStr("sk-ant-priced-workspace"))
    price = ModelPrice.model_validate(dict.fromkeys(ModelPrice.model_fields, "1000"))
    await replace_price_overrides(sessions, workspace, {"claude-test": price})
    mock = MockClaude([text_reply("one", input_tokens=30, output_tokens=7)])

    async with worker(postgres_url, redis_url, claude=mock, master_key_file=master_key):
        run_id = await submit_to(sessions, redis_url, workspace)
        await wait_for_status(sessions, run_id, "completed")

    [usage] = [e.payload for e in await list_run_events(sessions, run_id) if e.type == "usage"]
    assert (usage["model"], usage["estimated_usd"]) == ("claude-test", 0.037)
    summary = await get_run_summary(sessions, run_id)
    assert summary is not None
    assert (summary.usage.estimated_usd, summary.usage.cost_complete) == (Decimal("0.037"), True)


async def test_a_workspace_without_a_claude_key_fails_its_run(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, master_key: Path
) -> None:
    workspace_id = await new_workspace(sessions)
    mock = MockClaude([])

    async with worker(postgres_url, redis_url, claude=mock, master_key_file=master_key):
        run_id = await submit_to(sessions, redis_url, workspace_id)
        await wait_for_status(sessions, run_id, "failed")

    events = await list_run_events(sessions, run_id)
    assert [e.type for e in events] == ["run_started", "run_failed"]
    assert events[-1].payload["error"] == "workspace has no Claude connection"
    assert mock.requests == []
    run = await get_run(sessions, run_id)
    assert run is not None and run.attempt == 1


async def test_a_key_stored_under_another_master_key_fails_the_run_cleanly(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    master_key: Path,
    tmp_path: Path,
) -> None:
    workspace_id = await new_workspace(sessions)
    other = tmp_path / "other.key"
    generate_key_file(other)
    await put_connection(
        sessions,
        LocalKeyProvider.from_file(other),
        workspace_id,
        "claude",
        SecretStr("sk-ant-unreadable-here"),
    )

    async with worker(postgres_url, redis_url, claude=MockClaude([]), master_key_file=master_key):
        run_id = await submit_to(sessions, redis_url, workspace_id)
        await wait_for_status(sessions, run_id, "failed")

    [*_, failed] = await list_run_events(sessions, run_id)
    assert "cannot be decrypted" in str(failed.payload["error"])


async def test_a_writer_s_commit_survives_the_gate(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    """A run paused at a gate frees the worker but keeps its sandbox; after approval it carries
    on in that sandbox, so the branch the writer committed before the gate is still there."""
    repos, boxes = tmp_path / "repos", tmp_path / "sandboxes"
    make_repo(repos / "hello")
    boxes.mkdir()
    branch_log = BranchLog()
    sandboxes = RecordingSandboxes(
        FakeSandboxManager(local_root=repos, base_dir=boxes), inspect=branch_log
    )

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        repo = RepoSource(url=str(repos / "hello"))
        run_id = await submit(sessions, redis_url, load_spec("gate-approval.json"), repo)
        await wait_for_status(sessions, run_id, "waiting")
        await asyncio.wait_for(sandboxes.closed.wait(), 10)
        assert [p.name for p in boxes.iterdir()] == [f"agentic-sandbox-{run_id}"]  # kept
        assert branch_log.branches == [f"agent/{run_id}/writer"]

        await record_approval(sessions, run_id, "gate", GateDecision(decision="approve"))
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "completed")
        async with asyncio.timeout(10):
            while list(boxes.iterdir()):  # noqa: ASYNC110 (the sandbox is removed after the run)
                await asyncio.sleep(0.05)

    events = await list_run_events(sessions, run_id)
    assert [e.type for e in events if e.node_id == "gate"] == [
        "node_started",
        "gate_waiting",
        "gate_decided",
        "node_completed",
    ]
    resumed = next(e for e in events if e.type == "run_resumed")
    assert resumed.payload == {"attempt": 1, "completed_nodes": ["writer"]}
    name, email = COMMIT_AUTHOR
    assert branch_log.branches == [f"agent/{run_id}/writer"]
    assert branch_log.commits == [f"{name} <{email}>|Add NOTES.md", "NOTES.md"]


async def test_an_approval_s_edits_are_committed_on_the_writer_s_branch(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    """Done when (3.6), backend: the gate shows the writer's files, and an approval's edits are
    committed on its branch before the run goes on."""
    repos, boxes = tmp_path / "repos", tmp_path / "sandboxes"
    make_repo(repos / "hello")
    boxes.mkdir()
    branch_log = BranchLog()
    sandboxes = RecordingSandboxes(
        FakeSandboxManager(local_root=repos, base_dir=boxes), inspect=branch_log
    )

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        repo = RepoSource(url=str(repos / "hello"))
        run_id = await submit(sessions, redis_url, load_spec("gate-approval.json"), repo)
        await wait_for_status(sessions, run_id, "waiting")
        await asyncio.wait_for(sandboxes.closed.wait(), 10)
        sandboxes.closed.clear()
        waiting = [e for e in await list_run_events(sessions, run_id) if e.type == "gate_waiting"]
        assert waiting[-1].payload["changes"] == [
            {
                "node_id": "writer",
                "path": "NOTES.md",
                "old_path": None,
                "status": "added",
                "editable": True,
                "reason": None,
                "before": None,
                "after": "# Notes\n\nWritten by an agent.\n",
            }
        ]

        edit = FileEdit(node_id="writer", path="NOTES.md", content="# Notes\n\nReviewed.\n")
        decision = GateDecision(decision="approve", edits=[edit])
        await record_approval(sessions, run_id, "gate", decision)
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "completed")
        await asyncio.wait_for(sandboxes.closed.wait(), 10)

    events = await list_run_events(sessions, run_id)
    decided = next(e for e in events if e.type == "gate_decided")
    assert decided.payload["edits"] == [edit.model_dump(mode="json")]
    commits = decided.payload["commits"]
    assert isinstance(commits, dict) and set(commits) == {"writer"}
    name, email = COMMIT_AUTHOR
    assert branch_log.commits == [
        f"{name} <{email}>|Edit at gate gate",
        "NOTES.md",
        f"{name} <{email}>|Add NOTES.md",
        "NOTES.md",
    ]


async def test_cancelling_a_run_at_a_gate_removes_the_sandbox_it_kept(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    repos, boxes = tmp_path / "repos", tmp_path / "sandboxes"
    make_repo(repos / "hello")
    boxes.mkdir()
    sandboxes = RecordingSandboxes(FakeSandboxManager(local_root=repos, base_dir=boxes))

    async with worker(postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes):
        repo = RepoSource(url=str(repos / "hello"))
        run_id = await submit(sessions, redis_url, load_spec("gate-approval.json"), repo)
        await wait_for_status(sessions, run_id, "waiting")
        await asyncio.wait_for(sandboxes.closed.wait(), 10)
        assert [p.name for p in boxes.iterdir()] == [f"agentic-sandbox-{run_id}"]  # kept

        assert await request_cancel(sessions, run_id) == "waiting"
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "cancelled")

    assert list(boxes.iterdir()) == []
    events = await list_run_events(sessions, run_id)
    assert events[-1].type == "run_cancelled"
    assert events[-1].payload == {"reason": "cancelled by user"}
    assert "gate_decided" not in {e.type for e in events}


GITHUB_URL = "https://github.com/acme/hello"
GITHUB_TOKEN = "ghs_workertoken0005"


class MirroredSandboxes:
    """Sandboxes whose GitHub repos are cloned from a local mirror (no network), recording the
    `git_env` each clone was given."""

    def __init__(self, inner: SandboxManager, mirrors: Mapping[str, str]) -> None:
        self._inner, self._mirrors = inner, mirrors
        self.git_envs: list[dict[str, str] | None] = []
        self.closed = asyncio.Event()

    def keep(self, run_id: UUID) -> None:
        self._inner.keep(run_id)

    async def discard(self, run_id: UUID) -> None:
        await self._inner.discard(run_id)

    @asynccontextmanager
    async def open(
        self,
        run_id: UUID,
        repo: RepoSource,
        *,
        reuse: bool = False,
        git_env: Mapping[str, str] | None = None,
    ) -> AsyncGenerator[Sandbox]:
        self.git_envs.append(dict(git_env) if git_env is not None else None)
        local = RepoSource(url=self._mirrors.get(repo.url, repo.url), ref=repo.ref)
        try:
            async with self._inner.open(run_id, local, reuse=reuse) as box:
                yield box
        finally:
            self.closed.set()


async def submit_publishing_run(
    sessions: async_sessionmaker[AsyncSession], redis_url: str, workspace_id: UUID
) -> UUID:
    run_id = await create_run(
        sessions,
        load_spec("open-pr.json"),
        "go",
        RepoSource(url=GITHUB_URL),
        workspace_id=workspace_id,
    )
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()
    return run_id


def remote_branches(bare: Path) -> list[str]:
    out = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/agent"],
        cwd=bare,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.split()


@pytest.fixture
def debug_logs() -> Iterator[io.StringIO]:
    """Everything logged anywhere, at DEBUG, with the worker's redaction installed."""
    out = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(out)
    handler.setFormatter(JsonFormatter())
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    install_redaction(root)
    yield out
    root.removeHandler(handler)
    root.setLevel(level)


async def test_done_when_a_run_opens_a_pr_after_approval(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    debug_logs: io.StringIO,
) -> None:
    """Phase 1.8: the writer commits, the run waits at the gate with nothing pushed; after
    approval the branch is pushed (to a bare repo standing in for GitHub) and a pull request is
    opened (on a fake GitHub), recorded as `pr_opened`."""
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    remote = bare_remote(repos / "hello", tmp_path / "remote.git")
    github = FakeGithub(GITHUB_TOKEN)
    sandboxes = MirroredSandboxes(
        FakeSandboxManager(local_root=repos), {GITHUB_URL: str(repos / "hello")}
    )
    workspace_id = await new_workspace(sessions)
    await put_github_connection(sessions, workspace_id, 42, "acme")

    async with worker(
        postgres_url,
        redis_url,
        make_runtime=fake_with_tools,
        sandboxes=sandboxes,
        github=github,
        github_remote=lambda _full_name: remote,
    ):
        run_id = await submit_publishing_run(sessions, redis_url, workspace_id)
        await wait_for_status(sessions, run_id, "waiting")
        assert github.pulls == []
        assert remote_branches(tmp_path / "remote.git") == []

        await record_approval(sessions, run_id, "gate", GateDecision(decision="approve"))
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "completed")

    branch = f"agent/{run_id}/writer"
    events = await list_run_events(sessions, run_id)
    (opened,) = [e for e in events if e.type == "pr_opened"]
    assert opened.node_id == "publish"
    assert opened.payload["url"] == "https://github.com/acme/hello/pull/1"
    assert opened.payload["head"] == branch
    assert opened.payload["base"] == "main"
    assert remote_branches(tmp_path / "remote.git") == [branch]
    assert github.pulls[0]["title"] == "Add NOTES.md"
    # Both attempts cloned (or reopened) with the token as a header, never in an event.
    assert all(env is not None and "GIT_CONFIG_VALUE_0" in env for env in sandboxes.git_envs)
    assert not any(GITHUB_TOKEN in json.dumps(e.payload) for e in events)
    # Nor in the logs, plain or as the header git sends.
    header = base64.b64encode(f"x-access-token:{GITHUB_TOKEN}".encode()).decode()
    assert debug_logs.getvalue(), "nothing was logged, so the log check proves nothing"
    assert GITHUB_TOKEN not in debug_logs.getvalue()
    assert header not in debug_logs.getvalue()


async def test_a_publishing_run_without_a_github_connection_fails_cleanly(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    github = FakeGithub(GITHUB_TOKEN)
    sandboxes = MirroredSandboxes(
        FakeSandboxManager(local_root=repos), {GITHUB_URL: str(repos / "hello")}
    )
    workspace_id = await new_workspace(sessions)

    async with worker(
        postgres_url, redis_url, make_runtime=fake_with_tools, sandboxes=sandboxes, github=github
    ):
        run_id = await submit_publishing_run(sessions, redis_url, workspace_id)
        await wait_for_status(sessions, run_id, "failed")

    [*_, failed] = await list_run_events(sessions, run_id)
    assert failed.payload == {"error": "workspace has no GitHub connection"}
    assert sandboxes.git_envs == []  # failed before cloning
    assert github.tokens_issued == 0


DOCS_REPO = {
    "README.md": "# Acme\n",
    "pyproject.toml": "[tool.uv.workspace]\n",
    "packages/api/pyproject.toml": "[project]\nname = 'api'\n",
    "packages/engine/pyproject.toml": "[project]\nname = 'engine'\n",
    "web/package.json": "{}\n",
}
DOCS_MODULES = ["packages/api", "packages/engine", "web"]


def docs_page(input: str) -> Script:
    """A module agent's reply: a page for the module its input names."""
    path = json.loads(input)["path"]
    return [Message(text=f"<!-- module: {path} -->\n# {path}\n\nWhat {path} does."), ECHO_USAGE]


def docs_writer() -> Script:
    pages = {f"docs/{m.replace('/', '-')}.md": f"# {m}\n" for m in DOCS_MODULES}
    writes = [
        CallTool("repo.write_file", {"path": path, "content": content})
        for path, content in {"docs/README.md": "# Docs\n", **pages}.items()
    ]
    return [
        *writes,
        CallTool("repo.commit", {"message": "docs: generate module documentation"}),
        Message(text="committed the docs"),
        ECHO_USAGE,
        Completed(),
    ]


def remote_files(bare: Path, branch: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", branch],
        cwd=bare,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.split()


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_done_when_a_docs_run_opens_a_pr(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    decision: Literal["approve", "reject"],
) -> None:
    """Phase 1.11 (AC-1) on fakes: the "Generate docs" template lists the modules of a repo on
    GitHub, documents each in a map, and its writer commits the pages; the run waits at the
    gate with nothing pushed. Approval opens a pull request with the docs; rejection pushes
    nothing."""
    repos = tmp_path / "repos"
    make_repo(repos / "acme", DOCS_REPO)
    remote = bare_remote(repos / "acme", tmp_path / "remote.git")
    github = FakeGithub(GITHUB_TOKEN)
    sandboxes = MirroredSandboxes(
        FakeSandboxManager(local_root=repos), {GITHUB_URL: str(repos / "acme")}
    )
    workspace_id = await new_workspace(sessions)
    await put_github_connection(sessions, workspace_id, 42, "acme")
    runtimes: list[FakeRuntime] = []

    def make_runtime(tools: ToolExecutor | None) -> AgentRuntime:
        runtimes.append(FakeRuntime({"writer": docs_writer()}, default=docs_page, tools=tools))
        return runtimes[-1]

    async with worker(
        postgres_url,
        redis_url,
        make_runtime=make_runtime,
        sandboxes=sandboxes,
        github=github,
        github_remote=lambda _full_name: remote,
    ):
        run_id = await create_run(
            sessions,
            build_docs_spec(DocsParams()),
            "",
            RepoSource(url=GITHUB_URL),
            workspace_id=workspace_id,
        )
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
            await wait_for_status(sessions, run_id, "waiting")
            assert github.pulls == []
            assert remote_branches(tmp_path / "remote.git") == []

            await record_approval(
                sessions,
                run_id,
                "approve",
                GateDecision(decision=decision),
            )
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        ended = "completed" if decision == "approve" else "cancelled"
        await wait_for_status(sessions, run_id, ended)

    events = await list_run_events(sessions, run_id)
    (listed,) = [e for e in events if e.type == "tool_result" and e.node_id == "list_modules"]
    assert listed.payload["is_error"] is False
    items = [e.payload["index"] for e in events if e.type == "map_item_completed"]
    assert len(items) == 3 and all(i in items for i in (0, 1, 2))
    (writer_request,) = [r for rt in runtimes for r in rt.requests if r.node_id == "writer"]
    pages = writer_request.input.split(PAGE_SEPARATOR)
    assert [p.splitlines()[0] for p in pages] == [f"<!-- module: {m} -->" for m in DOCS_MODULES]

    branch = f"agent/{run_id}/writer"
    if decision == "reject":
        assert github.pulls == []
        assert remote_branches(tmp_path / "remote.git") == []
        return
    (opened,) = [e for e in events if e.type == "pr_opened"]
    assert opened.payload["head"] == branch
    assert github.pulls[0]["title"] == "docs: generate module documentation"
    assert set(remote_files(tmp_path / "remote.git", branch)) >= {
        "docs/README.md",
        "docs/packages-api.md",
        "docs/packages-engine.md",
        "docs/web.md",
    }


def test_the_engine_and_the_tool_servers_agree_on_tool_names() -> None:
    assert READ_TOOLS == READ_TOOL_NAMES
    assert WRITE_TOOLS == WRITE_TOOL_NAMES
    assert PUBLISH_TOOLS == PUBLISH_TOOL_NAMES


async def test_the_fake_github_app_clones_and_publishes_local_fixture_repos(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    """With `AGENTIC_GITHUB=fake` (dev and e2e tests), a docs run on a fake repo clones its bare
    repo under the sandbox root, runs on the default fake runtime, and after approval pushes the
    writer's branch there and opens a numbered pull request, with no call to GitHub."""
    fixtures = tmp_path / "fixtures"
    make_repo(tmp_path / "src", DOCS_REPO)
    bare = fixtures / "e2e-org" / "docs-demo.git"
    bare_remote(tmp_path / "src", bare)
    workspace_id = await new_workspace(sessions)
    await put_github_connection(sessions, workspace_id, 1, "e2e-org", "Organization")

    async with worker(
        postgres_url,
        redis_url,
        sandboxes=FakeSandboxManager(local_root=fixtures),
        agentic_github="fake",
        sandbox_local_root=fixtures,
    ):
        run_id = await create_run(
            sessions,
            build_docs_spec(DocsParams()),
            "",
            RepoSource(url="https://github.com/e2e-org/docs-demo"),
            workspace_id=workspace_id,
        )
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
            await wait_for_status(sessions, run_id, "waiting")
            await record_approval(sessions, run_id, "approve", GateDecision(decision="approve"))
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "completed")

    events = await list_run_events(sessions, run_id)
    (opened,) = [e for e in events if e.type == "pr_opened"]
    assert opened.payload["url"] == "https://github.com/e2e-org/docs-demo/pull/1"
    assert remote_branches(bare) == [f"agent/{run_id}/writer"]


def test_the_fake_github_app_is_refused_in_production(tmp_path: Path) -> None:
    from agentic_worker.main import ConfigError, build_github

    settings = WorkerSettings.model_validate(
        {"github": "fake", "sandbox_local_root": tmp_path, "env": "production"}
    )

    with pytest.raises(ConfigError, match="AGENTIC_ENV=production"):
        build_github(settings)


async def submit_limited(
    sessions: async_sessionmaker[AsyncSession],
    redis_url: str,
    spec: WorkflowSpec,
    **limits: int | Decimal,
) -> UUID:
    """Run `spec` in a new workspace with its own run limits."""
    workspace_id = await new_workspace(sessions)
    await replace_policy_overrides(sessions, workspace_id, PolicyOverrides.model_validate(limits))
    run_id = await create_run(sessions, spec, "go", workspace_id=workspace_id)
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()
    return run_id


async def test_a_run_past_its_wall_time_stops_cleanly_with_the_reason(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (3.2): exceeding a limit stops the run cleanly with a reason."""
    runtime = FakeRuntime({"reviewer": [Delay(30), ECHO_USAGE]})

    async with worker(postgres_url, redis_url, runtime=runtime):
        run_id = await submit_limited(sessions, redis_url, two_step_spec(), wall_time_s=1)
        await wait_for_status(sessions, run_id, "failed")

    events = await list_run_events(sessions, run_id)
    assert [(e.type, e.node_id) for e in events][-3:] == [
        ("node_cancelled", "reviewer"),
        ("policy_limit_exceeded", None),
        ("run_failed", None),
    ]
    over = events[-2].payload
    assert (over["limit"], over["value"]) == ("wall_time_s", 1)
    assert isinstance(over["observed"], int) and over["observed"] >= 1
    assert events[-1].payload == {"error": "policy limit: wall time of 1s exceeded"}
    summary = await get_run_summary(sessions, run_id)
    assert summary is not None
    assert summary.failure_reason == "policy limit: wall time of 1s exceeded"


def gated_spec() -> WorkflowSpec:
    """`writer`, a gate, then `after`; no tools, so no sandbox."""
    return parse_spec(
        {
            "spec_version": "0",
            "id": "gated",
            "name": "Gated",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {"type": "agent", "id": "writer", "role": "W", "instructions": "Go."},
                    {"type": "gate", "id": "approve", "title": "Go on?"},
                    {"type": "agent", "id": "after", "role": "A", "instructions": "Go."},
                ],
            },
        }
    )


async def test_time_waiting_at_a_gate_does_not_count_toward_wall_time(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with worker(postgres_url, redis_url):
        run_id = await submit_limited(sessions, redis_url, gated_spec(), wall_time_s=2)
        await wait_for_status(sessions, run_id, "waiting")
        await asyncio.sleep(2.5)  # longer than the run's wall time
        await record_approval(sessions, run_id, "approve", GateDecision(decision="approve"))
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "completed")

    assert await active_seconds(sessions, run_id) < 2


async def test_wall_time_carries_over_a_worker_restart(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """The time a run spent on an earlier attempt counts, up to that attempt's last event: the
    next worker stops it sooner."""
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    first = FakeRuntime({"writer": [Delay(2), ECHO_USAGE], "reviewer": [Delay(30), ECHO_USAGE]})
    async with worker(postgres_url, redis_url, runtime=first, checkpointer=checkpointer):
        run_id = await submit_limited(sessions, redis_url, two_step_spec(), wall_time_s=3)
        await wait_for_event(sessions, run_id, "node_started", "reviewer")
    spent = await active_seconds(sessions, run_id)

    again = FakeRuntime({"reviewer": [Delay(30), ECHO_USAGE]})
    loop = asyncio.get_running_loop()
    async with worker(postgres_url, redis_url, runtime=again, checkpointer=checkpointer):
        resumed_at = loop.time()
        await wait_for_status(sessions, run_id, "failed")
        took = loop.time() - resumed_at

    assert spent >= 1.9
    assert took < 2.5  # what was left (about 1 s) and the worker's start, not 3 s
    events = await list_run_events(sessions, run_id)
    assert [e.type for e in events][-2:] == ["policy_limit_exceeded", "run_failed"]
    assert events[-2].payload["observed"] == 3


def costing(usd: float, then: float = 0.0) -> Script:
    """An agent turn whose usage costs `usd`, ending `then` seconds later."""
    return [
        Usage(model="m", input_tokens=1, output_tokens=1, estimated_usd=usd),
        Delay(then),
        Message(text="done"),
    ]


async def test_a_run_over_its_budget_stops_cleanly_with_the_reason(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (3.3): AC-7 for a budgeted run."""
    runtime = FakeRuntime({"writer": costing(0.6), "reviewer": costing(0.6)})

    async with worker(postgres_url, redis_url, runtime=runtime):
        run_id = await submit_limited(sessions, redis_url, two_step_spec(), budget_usd=Decimal("1"))
        await wait_for_status(sessions, run_id, "failed")

    events = await list_run_events(sessions, run_id)
    assert [(e.type, e.node_id) for e in events][-3:] == [
        ("node_cancelled", "reviewer"),
        ("policy_limit_exceeded", "reviewer"),
        ("run_failed", None),
    ]
    assert events[-2].payload == {"limit": "budget_usd", "value": "1", "observed": "1.2"}
    summary = await get_run_summary(sessions, run_id)
    assert summary is not None
    assert summary.failure_reason == "policy limit: budget of $1.00 reached ($1.20 spent)"
    assert summary.usage.estimated_usd == Decimal("1.2")
    assert summary.usage.budget_usd == Decimal("1")


async def test_an_unbudgeted_run_continues_and_still_reports_its_cost(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (3.3): without a budget there is no cap."""
    runtime = FakeRuntime({"writer": costing(60), "reviewer": costing(60)})

    async with worker(postgres_url, redis_url, runtime=runtime):
        run_id = await submit_limited(sessions, redis_url, two_step_spec())
        await wait_for_status(sessions, run_id, "completed")

    summary = await get_run_summary(sessions, run_id)
    assert summary is not None
    assert summary.usage.estimated_usd == Decimal("120")
    assert summary.usage.budget_usd is None


async def test_spend_carries_over_a_worker_restart(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """The next worker counts what the cut-off attempt spent: alone, the reviewer's $0.50 is
    under the budget."""
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    first = FakeRuntime({"writer": costing(0.6), "reviewer": [Delay(30), ECHO_USAGE]})
    async with worker(postgres_url, redis_url, runtime=first, checkpointer=checkpointer):
        run_id = await submit_limited(sessions, redis_url, two_step_spec(), budget_usd=Decimal("1"))
        await wait_for_event(sessions, run_id, "node_started", "reviewer")

    again = FakeRuntime({"reviewer": costing(0.5)})
    async with worker(postgres_url, redis_url, runtime=again, checkpointer=checkpointer):
        await wait_for_status(sessions, run_id, "failed")

    events = await list_run_events(sessions, run_id)
    assert [e.type for e in events][-2:] == ["policy_limit_exceeded", "run_failed"]
    assert events[-2].payload["observed"] == "1.1"


async def test_spend_before_a_gate_counts_and_the_budget_stays_frozen(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    runtime = FakeRuntime({"writer": costing(0.6), "after": costing(0.6)})

    async with worker(postgres_url, redis_url, runtime=runtime):
        run_id = await submit_limited(sessions, redis_url, gated_spec(), budget_usd=Decimal("1"))
        await wait_for_status(sessions, run_id, "waiting")
        stored = await get_run(sessions, run_id)
        assert stored is not None
        # Raising the workspace's default does not change a run that already exists.
        await replace_policy_overrides(
            sessions, stored.workspace_id, PolicyOverrides(budget_usd=Decimal("100"))
        )
        await record_approval(sessions, run_id, "approve", GateDecision(decision="approve"))
        redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
        try:
            await enqueue_run(redis, run_id)
        finally:
            await redis.aclose()
        await wait_for_status(sessions, run_id, "failed")

    events = await list_run_events(sessions, run_id)
    assert [(e.type, e.node_id) for e in events][-3:] == [
        ("node_cancelled", "after"),
        ("policy_limit_exceeded", "after"),
        ("run_failed", None),
    ]
    assert events[-2].payload["observed"] == "1.2"
