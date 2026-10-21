import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import docker
import pytest
from docker.errors import DockerException
from langgraph.checkpoint.memory import InMemorySaver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.graph import Checkpointer, checkpoint_serde
from agentic_engine.logging import JsonFormatter
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import AgentRuntime, ClaudeRuntime, Failed, ToolExecutor
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime
from agentic_runtime.testing import MOCK_API_KEY, MockClaude, text_reply
from agentic_sandbox import FakeSandboxManager, RepoSource, Sandbox, SandboxManager
from agentic_sandbox.docker_backend import RUN_LABEL, DockerSandboxManager
from agentic_sandbox.testing import make_repo
from agentic_store import create_run, enqueue_run, get_run, list_run_events
from agentic_tools.repo import open_repo_tools
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
) -> AsyncGenerator[asyncio.Event]:
    """A worker running in this event loop; yields its stop event and stops it on exit.

    Its checkpoints are kept in memory (psycopg cannot run on the Windows test loop); pass one
    `checkpointer` to workers that must share them."""
    stop, ready = asyncio.Event(), asyncio.Event()
    checkpointer = checkpointer or InMemorySaver(serde=checkpoint_serde())
    settings = WorkerSettings(
        database_url=postgres_url, redis_url=redis_url, ready_file=ready_file, queue_poll_s=0.1
    )
    task = asyncio.create_task(
        run(
            settings,
            stop,
            ready,
            runtime=runtime,
            make_runtime=make_runtime,
            sandboxes=sandboxes,
            checkpointer=checkpointer,
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
    async with asyncio.timeout(10):
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
    """Wraps a `SandboxManager`, noting in `order` when each sandbox is closed."""

    def __init__(self, inner: SandboxManager, order: list[str]) -> None:
        self._inner, self._order = inner, order

    @asynccontextmanager
    async def open(self, run_id: UUID, repo: RepoSource) -> AsyncGenerator[Sandbox]:
        try:
            async with self._inner.open(run_id, repo) as box:
                yield box
        finally:
            self._order.append("sandbox closed")


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
    async def recording_tools(sandbox: Sandbox) -> AsyncGenerator[ToolExecutor]:
        try:
            async with open_repo_tools(sandbox) as tools:
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
            if not client.containers.list(all=True, filters={"label": f"{RUN_LABEL}={run_id}"}):
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
            if not client.containers.list(all=True, filters={"label": f"{RUN_LABEL}={run_id}"}):
                break
            await asyncio.sleep(0.1)
