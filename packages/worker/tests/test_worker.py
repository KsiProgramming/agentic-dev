import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.logging import JsonFormatter
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import AgentRuntime, ClaudeRuntime, Failed
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime
from agentic_runtime.testing import MOCK_API_KEY, MockClaude, text_reply
from agentic_store import create_run, enqueue_run, get_run, list_run_events
from agentic_worker.main import WorkerSettings, run

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"


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
    ready_file: Path | None = None,
) -> AsyncGenerator[asyncio.Event]:
    """A worker running in this event loop; yields its stop event and stops it on exit."""
    stop, ready = asyncio.Event(), asyncio.Event()
    settings = WorkerSettings(
        database_url=postgres_url, redis_url=redis_url, ready_file=ready_file, queue_poll_s=0.1
    )
    task = asyncio.create_task(run(settings, stop, ready, runtime=runtime))
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


async def submit(
    sessions: async_sessionmaker[AsyncSession], redis_url: str, spec: WorkflowSpec
) -> UUID:
    run_id = await create_run(sessions, spec, "go")
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()
    return run_id


pytestmark = pytest.mark.integration


async def test_worker_starts_and_stops(
    postgres_url: str, redis_url: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
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


async def test_stopping_the_worker_cancels_the_run_in_flight(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    runtime = FakeRuntime({"writer": [Delay(30), ECHO_USAGE]})
    async with worker(postgres_url, redis_url, runtime=runtime):
        run_id = await submit(sessions, redis_url, two_step_spec())
        await wait_for_status(sessions, run_id, "running")

    run_after = await get_run(sessions, run_id)
    assert run_after is not None
    assert run_after.status == "cancelled"
    assert (await list_run_events(sessions, run_id))[-1].type == "run_cancelled"


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
