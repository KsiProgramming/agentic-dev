"""`POST /runs` and `GET /runs/{id}/events` against a real server, worker, Postgres and Redis.

The app is served by uvicorn on a local port and the stream is read as raw `text/event-stream`
over HTTP, the way `curl -N` reads it.
"""

import asyncio
import json
import socket
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_runtime import AgentRuntime, Failed
from agentic_runtime.fake import FakeRuntime
from agentic_store import RUN_QUEUE, Run, get_run
from agentic_worker.main import WorkerSettings
from agentic_worker.main import run as run_worker

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs"


def spec_json(name: str) -> dict[str, Any]:
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Frame:
    id: int
    event: str
    data: dict[str, Any]


async def read_frames(lines: AsyncIterator[str]) -> AsyncIterator[Frame]:
    """Parse an SSE body into frames, skipping comments (keep-alive pings)."""
    fields: dict[str, str] = {}
    async for line in lines:
        if line == "":
            if fields:
                yield Frame(int(fields["id"]), fields["event"], json.loads(fields["data"]))
            fields = {}
        elif not line.startswith(":"):
            name, _, value = line.partition(":")
            fields[name] = value.removeprefix(" ")


@asynccontextmanager
async def api(postgres_url: str, redis_url: str) -> AsyncGenerator[httpx.AsyncClient]:
    """The API served by uvicorn on a free local port, and a client for it."""
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:  # noqa: ASYNC110 (uvicorn offers no event to await)
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            yield client
    finally:
        server.should_exit = True
        await task


@asynccontextmanager
async def worker(
    postgres_url: str,
    redis_url: str,
    *,
    step_delay_s: float = 0,
    runtime: AgentRuntime | None = None,
) -> AsyncGenerator[None]:
    """A worker running in this event loop until the context exits."""
    stop, ready = asyncio.Event(), asyncio.Event()
    settings = WorkerSettings(
        database_url=postgres_url,
        redis_url=redis_url,
        queue_poll_s=0.1,
        fake_step_delay_s=step_delay_s,
        # Never the runtime a developer's `.env` selects (it may be Claude with a real key).
        runtime="fake",
    )
    task = asyncio.create_task(run_worker(settings, stop, ready, runtime=runtime))
    try:
        async with asyncio.timeout(10):
            await ready.wait()
        yield
    finally:
        stop.set()
        async with asyncio.timeout(5):
            await task


async def post_run(client: httpx.AsyncClient, spec: str = "valid/two-step-sequence.json") -> UUID:
    response = await client.post("/runs", json={"workflow": spec_json(spec), "input": "go"})
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"])


async def stream(
    client: httpx.AsyncClient, run_id: UUID, **kwargs: Any
) -> AsyncIterator[tuple[float, Frame]]:
    """Each frame of a run's event stream with the time it arrived."""
    async with client.stream("GET", f"/runs/{run_id}/events", **kwargs) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for frame in read_frames(response.aiter_lines()):
            yield time.monotonic(), frame


async def collect(client: httpx.AsyncClient, run_id: UUID, **kwargs: Any) -> list[Frame]:
    async with asyncio.timeout(15):
        return [frame async for _, frame in stream(client, run_id, **kwargs)]


async def queued_ids(redis_url: str) -> list[str]:
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        items: list[Any] = await redis.lrange(RUN_QUEUE, 0, -1)  # pyright: ignore[reportUnknownMemberType]
        return [bytes(item).decode() for item in items]
    finally:
        await redis.aclose()


async def count_runs(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return await session.scalar(select(func.count()).select_from(Run)) or 0


async def test_post_run_queues_it(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("valid/two-step-sequence.json"), "input": "go"}
        )

    assert response.status_code == 202
    body = response.json()
    run_id = UUID(body["run_id"])
    assert body["status"] == "queued"
    assert body["events_url"] == f"{client.base_url}/runs/{run_id}/events"
    run = await get_run(sessions, run_id)
    assert run is not None
    assert (run.status, run.input, run.spec.id) == ("queued", "go", "draft-and-review")
    assert str(run_id) in await queued_ids(redis_url)


async def test_post_run_rejects_an_invalid_spec(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    runs_before, queue_before = await count_runs(sessions), await queued_ids(redis_url)
    async with api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("invalid/unknown-node-type.json")}
        )

    assert response.status_code == 422
    assert await count_runs(sessions) == runs_before
    assert await queued_ids(redis_url) == queue_before


async def test_stream_delivers_a_live_run_in_order(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (0.6): `curl` streams events of a live run."""
    async with (
        worker(postgres_url, redis_url, step_delay_s=0.05),
        api(postgres_url, redis_url) as client,
    ):
        run_id = await post_run(client)
        received: list[tuple[float, Frame]] = []
        status_at_first_frame = None
        async with asyncio.timeout(15):
            async for arrived, frame in stream(client, run_id):
                if not received:
                    run = await get_run(sessions, run_id)
                    status_at_first_frame = run.status if run else None
                received.append((arrived, frame))

    frames = [frame for _, frame in received]
    assert [f.id for f in frames] == list(range(1, len(frames) + 1))
    assert frames[0].event == "run_started"
    assert frames[-1].event == "run_completed"
    assert "text_delta" in {f.event for f in frames}
    assert all(f.data["run_id"] == str(run_id) and f.data["seq"] == f.id for f in frames)
    # Events reached the client while the run was still going, not all at the end.
    assert status_at_first_frame == "running"
    assert received[-1][0] - received[0][0] > 0.3
    run = await get_run(sessions, run_id)
    assert run is not None
    assert run.status == "completed"


async def test_stream_of_a_finished_run_replays_and_closes(
    postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        async with worker(postgres_url, redis_url):
            run_id = await post_run(client)
            live = await collect(client, run_id)

        replayed = await collect(client, run_id)

    assert replayed == live
    assert replayed[-1].event == "run_completed"


async def test_stream_resumes_after_last_event_id(postgres_url: str, redis_url: str) -> None:
    async with api(postgres_url, redis_url) as client:
        async with worker(postgres_url, redis_url):
            run_id = await post_run(client)
            everything = await collect(client, run_id)

        by_header = await collect(client, run_id, headers={"Last-Event-ID": "3"})
        by_query = await collect(client, run_id, params={"after": 3})
        # A reconnecting EventSource keeps the URL's `after` and adds the header; the header wins.
        reconnect = await collect(
            client, run_id, params={"after": 1}, headers={"Last-Event-ID": "5"}
        )

    assert by_header == by_query == everything[3:]
    assert reconnect == everything[5:]


async def test_stream_of_an_unknown_run_is_404(postgres_url: str, redis_url: str) -> None:
    async with api(postgres_url, redis_url) as client:
        response = await client.get(f"/runs/{uuid4()}/events")

    assert response.status_code == 404


async def test_a_failed_run_streams_run_failed_and_the_worker_carries_on(
    postgres_url: str, redis_url: str
) -> None:
    runtime = FakeRuntime({"writer": [Failed(error="boom")]})
    async with (
        worker(postgres_url, redis_url, runtime=runtime),
        api(postgres_url, redis_url) as client,
    ):
        failed = await collect(client, await post_run(client))
        next_run = await collect(client, await post_run(client, "valid/single-agent.json"))

    assert failed[-1].event == "run_failed"
    assert failed[-1].data["payload"] == {"stopped_at": "writer"}
    assert next_run[-1].event == "run_completed"


async def test_post_run_stores_the_repo(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    repo = {"url": "https://github.com/octo/hello.git", "ref": "main"}
    async with api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("valid/list-repo-files.json"), "repo": repo}
        )

    assert response.status_code == 202, response.text
    run = await get_run(sessions, UUID(response.json()["run_id"]))
    assert run is not None
    assert run.repo is not None
    assert run.repo.model_dump() == repo


async def test_repo_tools_need_a_repo(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    runs_before = await count_runs(sessions)
    async with api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("valid/list-repo-files.json")}
        )

    assert response.status_code == 422
    assert "node 'explorer' uses repo.list_files, which need a `repo`" in response.text
    assert await count_runs(sessions) == runs_before


@pytest.mark.parametrize(
    "repo",
    [
        {"url": "git@github.com:octo/hello.git"},
        {"url": "https://user:token@github.com/octo/hello.git"},
        {"url": "https://github.com/octo/hello.git", "ref": "--upload-pack=x"},
        {"url": "https://github.com/octo/hello.git", "depth": 5},
    ],
)
async def test_unsafe_repos_are_rejected(
    postgres_url: str, redis_url: str, repo: dict[str, Any]
) -> None:
    async with api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("valid/list-repo-files.json"), "repo": repo}
        )

    assert response.status_code == 422
