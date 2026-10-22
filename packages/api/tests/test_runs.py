"""`POST /runs` and `GET /runs/{id}/events` against a real server, worker, Postgres and Redis.

The app is served by uvicorn on a local port and the stream is read as raw `text/event-stream`
over HTTP, the way `curl -N` reads it.
"""

import asyncio
import contextlib
import itertools
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
from langgraph.checkpoint.memory import InMemorySaver
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.runs import routes
from agentic_api.settings import Settings
from agentic_engine.events import RunEventLog
from agentic_engine.graph import checkpoint_serde
from agentic_engine.spec import parse_spec
from agentic_runtime import AgentRuntime, Failed
from agentic_runtime.fake import FakeRuntime
from agentic_store import (
    DEFAULT_WORKSPACE_ID,
    RUN_QUEUE,
    PostgresEventSink,
    Run,
    Workspace,
    create_run,
    delete_connection,
    get_run,
    get_run_summary,
    put_github_connection,
)
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


async def read_sse(lines: AsyncIterator[str]) -> AsyncIterator[dict[str, str]]:
    """Parse an SSE body into the fields of each frame, skipping comments (keep-alive pings)."""
    fields: dict[str, str] = {}
    async for line in lines:
        if line == "":
            if fields:
                yield fields
            fields = {}
        elif not line.startswith(":"):
            name, _, value = line.partition(":")
            fields[name] = value.removeprefix(" ")


async def read_frames(lines: AsyncIterator[str]) -> AsyncIterator[Frame]:
    """Parse a run's event stream into frames."""
    async for fields in read_sse(lines):
        yield Frame(int(fields["id"]), fields["event"], json.loads(fields["data"]))


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
    # Checkpoints in memory: psycopg cannot run on the Windows test loop.
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    task = asyncio.create_task(
        run_worker(settings, stop, ready, runtime=runtime, checkpointer=checkpointer)
    )
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
) -> AsyncGenerator[tuple[float, Frame]]:
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


async def test_a_tool_node_on_repo_tools_needs_a_repo(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    runs_before = await count_runs(sessions)
    async with api(postgres_url, redis_url) as client:
        response = await client.post("/runs", json={"workflow": spec_json("valid/tool-node.json")})

    assert response.status_code == 422
    assert "node 'list' uses repo.list_files, which need a `repo`" in response.text
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


def gated_spec() -> dict[str, Any]:
    """The gate fixture without its `repo.*` tools, so it runs with no sandbox."""
    spec = spec_json("valid/gate-approval.json")
    spec["root"]["steps"][0]["tools"] = []
    spec["root"]["steps"][2] = {"type": "agent", "id": "list", "role": "L", "instructions": "Go."}
    return spec


async def until_waiting(client: httpx.AsyncClient, run_id: UUID) -> list[Frame]:
    """The run's frames up to its `gate_waiting`; the stream itself stays open."""
    frames: list[Frame] = []
    async with asyncio.timeout(15), contextlib.aclosing(stream(client, run_id)) as frames_in:
        async for _, frame in frames_in:
            frames.append(frame)
            if frame.event == "gate_waiting":
                return frames
    raise AssertionError(f"the run ended without pausing: {[f.event for f in frames]}")


async def post_gated_run(client: httpx.AsyncClient) -> UUID:
    response = await client.post("/runs", json={"workflow": gated_spec(), "input": "go"})
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"])


async def test_done_when_a_run_pauses_at_a_gate_and_resumes_on_approval(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """Done when (1.7): a run pauses at a gate and resumes on approval."""
    async with worker(postgres_url, redis_url), api(postgres_url, redis_url) as client:
        run_id = await post_gated_run(client)
        paused = await until_waiting(client, run_id)
        run = await get_run(sessions, run_id)
        assert run is not None and run.status == "waiting"

        response = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "gate", "decision": "approve"}
        )
        assert response.status_code == 202, response.text
        assert response.json() == {
            "run_id": str(run_id),
            "node_id": "gate",
            "decision": "approve",
            "status": "queued",
        }
        rest = await collect(client, run_id, headers={"Last-Event-ID": str(paused[-1].id)})

    assert paused[-1].data["node_id"] == "gate"
    assert paused[-1].data["payload"]["title"] == "Approve the notes"
    events = [(f.event, f.data["node_id"]) for f in rest if f.event.startswith(("gate_", "run_"))]
    assert events == [("run_resumed", None), ("gate_decided", "gate"), ("run_completed", None)]
    assert [f.id for f in paused + rest] == list(range(1, len(paused) + len(rest) + 1))
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "completed"


async def test_a_rejected_gate_cancels_the_run(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with worker(postgres_url, redis_url), api(postgres_url, redis_url) as client:
        run_id = await post_gated_run(client)
        paused = await until_waiting(client, run_id)
        response = await client.post(
            f"/runs/{run_id}/approvals",
            json={"node_id": "gate", "decision": "reject", "comment": "not now"},
        )
        assert response.status_code == 202, response.text
        rest = await collect(client, run_id, headers={"Last-Event-ID": str(paused[-1].id)})

    assert rest[-1].event == "run_cancelled"
    assert rest[-1].data["payload"] == {"stopped_at": "gate"}
    assert "list" not in {f.data["node_id"] for f in rest}
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "cancelled"


async def test_approvals_that_do_not_fit_are_refused(postgres_url: str, redis_url: str) -> None:
    async with worker(postgres_url, redis_url), api(postgres_url, redis_url) as client:
        unknown = await client.post(
            f"/runs/{uuid4()}/approvals", json={"node_id": "gate", "decision": "approve"}
        )
        run_id = await post_gated_run(client)
        await until_waiting(client, run_id)
        wrong_gate = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "writer", "decision": "approve"}
        )
        bad_decision = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "gate", "decision": "maybe"}
        )
        first = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "gate", "decision": "approve"}
        )
        again = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "gate", "decision": "approve"}
        )
        await collect(client, run_id)

    assert unknown.status_code == 404
    assert wrong_gate.status_code == 409
    assert "waiting at gate 'gate', not 'writer'" in wrong_gate.text
    assert bad_decision.status_code == 422
    assert first.status_code == 202
    assert again.status_code == 409


GITHUB_REPO = {"url": "https://github.com/acme/hello"}


def without_gate() -> dict[str, Any]:
    spec = spec_json("valid/open-pr.json")
    spec["root"]["steps"] = [s for s in spec["root"]["steps"] if s["type"] != "gate"]
    return spec


@asynccontextmanager
async def github_connected(sessions: async_sessionmaker[AsyncSession]) -> AsyncGenerator[None]:
    """The default workspace linked to a GitHub App installation, for the duration."""
    await put_github_connection(sessions, DEFAULT_WORKSPACE_ID, 42, "acme")
    try:
        yield
    finally:
        await delete_connection(sessions, DEFAULT_WORKSPACE_ID, "github")


async def test_a_publishing_run_is_queued_when_github_is_connected(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with github_connected(sessions), api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("valid/open-pr.json"), "repo": GITHUB_REPO}
        )

    assert response.status_code == 202, response.text
    # Off the queue again: no later test's worker may try to clone from GitHub.
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await redis.lrem(RUN_QUEUE, 0, response.json()["run_id"])  # pyright: ignore[reportUnknownMemberType]
    finally:
        await redis.aclose()


async def test_publishing_without_a_gate_is_refused(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    runs_before = await count_runs(sessions)
    async with github_connected(sessions), api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": without_gate(), "repo": GITHUB_REPO}
        )

    assert response.status_code == 422
    assert "node 'publish': github.openPR must come after a gate that follows 'writer'" in (
        response.text
    )
    assert await count_runs(sessions) == runs_before


@pytest.mark.parametrize(
    ("repo", "message"),
    [
        (None, "which need a `repo`"),
        ({"url": "https://gitlab.com/acme/hello"}, "which need a `repo` on GitHub"),
    ],
)
async def test_publishing_needs_a_repo_on_github(
    postgres_url: str, redis_url: str, repo: dict[str, Any] | None, message: str
) -> None:
    body: dict[str, Any] = {"workflow": spec_json("valid/open-pr.json")}
    if repo is not None:
        body["repo"] = repo
    async with api(postgres_url, redis_url) as client:
        response = await client.post("/runs", json=body)

    assert response.status_code == 422
    assert message in response.text


async def test_publishing_needs_a_github_connection(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    await delete_connection(sessions, DEFAULT_WORKSPACE_ID, "github")
    runs_before = await count_runs(sessions)
    async with api(postgres_url, redis_url) as client:
        response = await client.post(
            "/runs", json={"workflow": spec_json("valid/open-pr.json"), "repo": GITHUB_REPO}
        )

    assert response.status_code == 409
    assert "no GitHub connection" in response.text
    assert await count_runs(sessions) == runs_before


DOCS_RUN: dict[str, Any] = {
    "template": {"id": "generate-docs", "parameters": {"output_dir": "documentation"}},
    "repo": GITHUB_REPO,
}


async def test_a_template_run_stores_the_spec_it_builds(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with github_connected(sessions), api(postgres_url, redis_url) as client:
        response = await client.post("/runs", json=DOCS_RUN)

    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await redis.lrem(RUN_QUEUE, 0, run_id)  # pyright: ignore[reportUnknownMemberType]
    finally:
        await redis.aclose()
    run = await get_run(sessions, UUID(run_id))
    assert run is not None
    assert run.spec.id == "generate-docs"
    assert "`documentation/README.md`" in run.spec.model_dump_json()
    summary = await get_run_summary(sessions, UUID(run_id))
    assert summary is not None and summary.template_id == "generate-docs"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({**DOCS_RUN, "workflow": spec_json("valid/open-pr.json")}, "either `workflow` or"),
        ({"repo": GITHUB_REPO}, "either `workflow` or `template`"),
        ({**DOCS_RUN, "template": {"id": "nope"}}, "unknown template 'nope'"),
        (
            {**DOCS_RUN, "template": {"id": "generate-docs", "parameters": {"output_dir": "../x"}}},
            "parameters.output_dir:",
        ),
        (
            {**DOCS_RUN, "template": {"id": "generate-docs", "parameters": {"colour": "red"}}},
            "parameters.colour: Extra inputs are not permitted",
        ),
        ({"template": DOCS_RUN["template"]}, "uses repo.list_modules, which need a `repo`"),
    ],
)
async def test_bad_template_runs_are_refused(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    body: dict[str, Any],
    message: str,
) -> None:
    runs_before = await count_runs(sessions)
    async with api(postgres_url, redis_url) as client:
        response = await client.post("/runs", json=body)

    assert response.status_code == 422
    assert message in response.text
    assert await count_runs(sessions) == runs_before


# `GET /runs/stream`: live run summaries of a workspace.


@asynccontextmanager
async def summaries(
    client: httpx.AsyncClient, workspace_id: UUID | None = None
) -> AsyncGenerator[AsyncIterator[dict[str, Any]]]:
    """The `RunSummary` of each `run_summary` frame of the workspace's summaries stream."""
    params = {"workspace_id": str(workspace_id)} if workspace_id else {}
    async with client.stream("GET", "/runs/stream", params=params) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        async def frames() -> AsyncIterator[dict[str, Any]]:
            async for fields in read_sse(response.aiter_lines()):
                assert fields["event"] == "run_summary"
                yield json.loads(fields["data"])

        yield frames()


async def summaries_until(
    frames: AsyncIterator[dict[str, Any]], run_id: UUID, status: str
) -> list[dict[str, Any]]:
    """Every summary streamed up to the one where `run_id` has `status`."""
    seen: list[dict[str, Any]] = []
    async with asyncio.timeout(15):
        async for summary in frames:
            seen.append(summary)
            if summary["id"] == str(run_id) and summary["status"] == status:
                return seen
    raise AssertionError(f"the stream ended before {run_id} was {status}")


def statuses_of(seen: list[dict[str, Any]], run_id: UUID) -> list[str]:
    return [s["status"] for s in seen if s["id"] == str(run_id)]


@pytest.fixture
async def workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name="summaries stream"))
    return workspace_id


async def add_run(sessions: async_sessionmaker[AsyncSession], workspace_id: UUID) -> RunEventLog:
    """A queued run of `workspace_id` and the log to write its events through the sink."""
    spec = parse_spec(spec_json("valid/two-step-sequence.json"))
    run_id = await create_run(sessions, spec, "go", None, workspace_id)
    return RunEventLog(run_id, PostgresEventSink(sessions))


async def test_the_summaries_stream_follows_a_gated_run(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    """A run's status changes reach the runs list live: waiting at the gate, then completed
    after approval. Changes made within one read (queued, running) may arrive as the latest
    one only."""
    async with (
        worker(postgres_url, redis_url),
        api(postgres_url, redis_url) as client,
        summaries(client) as frames,
    ):
        run_id = await post_gated_run(client)
        seen = await summaries_until(frames, run_id, "waiting")
        assert seen[-1]["waiting_gate"] == {"node_id": "gate", "title": "Approve the notes"}

        response = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "gate", "decision": "approve"}
        )
        assert response.status_code == 202, response.text
        seen += await summaries_until(frames, run_id, "completed")

    statuses = statuses_of(seen, run_id)
    assert statuses.index("waiting") < statuses.index("completed")
    mine = [s for s in seen if s["id"] == str(run_id)]
    assert all(a != b for a, b in itertools.pairwise(mine)), "a summary was sent twice"
    assert mine[-1]["waiting_gate"] is None
    assert mine[-1]["duration_ms"] is not None


async def test_the_summaries_stream_skips_unchanged_runs_and_other_workspaces(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, workspace: UUID
) -> None:
    other = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=other, name="other"))

    async with api(postgres_url, redis_url) as client, summaries(client, workspace) as frames:
        log = await add_run(sessions, workspace)
        elsewhere = await add_run(sessions, other)
        await log.emit("run_started")
        await elsewhere.emit("run_started")
        # Text deltas do not change the summary, so they send nothing.
        for text in ("a", "b", "c"):
            await log.emit("text_delta", node_id="draft", payload={"text": text})
            await asyncio.sleep(0.3)
        await elsewhere.emit("run_completed")
        await log.emit("run_completed")
        seen = await summaries_until(frames, log.run_id, "completed")

    assert {s["id"] for s in seen} == {str(log.run_id)}
    statuses = statuses_of(seen, log.run_id)
    assert statuses.count("running") == 1
    assert statuses[-1] == "completed"


async def test_the_summaries_stream_rechecks_without_a_notification(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    workspace: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost notification (or one missed while the listener reconnected) delays a change by
    at most `RECHECK_S`; it is never dropped."""
    monkeypatch.setattr(routes, "RECHECK_S", 0.3)
    async with api(postgres_url, redis_url) as client, summaries(client, workspace) as frames:
        log = await add_run(sessions, workspace)
        await summaries_until(frames, log.run_id, "queued")
        # Changed behind the sink's back: no NOTIFY is sent.
        async with sessions.begin() as session:
            await session.execute(
                update(Run)
                .where(Run.id == log.run_id)
                .values(status="cancelled", updated_at=func.now())
            )
        seen = await summaries_until(frames, log.run_id, "cancelled")

    assert statuses_of(seen, log.run_id) == ["cancelled"]


async def test_the_summaries_stream_of_an_unknown_workspace_is_404(
    postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        response = await client.get("/runs/stream", params={"workspace_id": str(uuid4())})

    assert response.status_code == 404


async def post_slow_run(client: httpx.AsyncClient) -> UUID:
    response = await client.post(
        "/runs",
        json={"workflow": spec_json("valid/single-agent.json"), "input": "one two three four five"},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"])


async def until_event(client: httpx.AsyncClient, run_id: UUID, event: str) -> list[Frame]:
    """The run's frames up to its first `event`; the stream itself stays open."""
    frames: list[Frame] = []
    async with asyncio.timeout(15), contextlib.aclosing(stream(client, run_id)) as frames_in:
        async for _, frame in frames_in:
            frames.append(frame)
            if frame.event == event:
                return frames
    raise AssertionError(f"no {event}: {[f.event for f in frames]}")


async def test_a_running_run_is_cancelled_within_seconds(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with (
        worker(postgres_url, redis_url, step_delay_s=0.5),
        api(postgres_url, redis_url) as client,
    ):
        run_id = await post_slow_run(client)
        started = await until_event(client, run_id, "text_delta")
        response = await client.post(f"/runs/{run_id}/cancel")
        again = await client.post(f"/runs/{run_id}/cancel")
        rest = await collect(client, run_id, headers={"Last-Event-ID": str(started[-1].id)})

    assert response.status_code == 202, response.text
    assert response.json() == {"run_id": str(run_id), "status": "cancelling"}
    assert again.status_code == 202
    assert [f.event for f in rest][-2:] == ["node_cancelled", "run_cancelled"]
    assert rest[-1].data["payload"] == {"reason": "cancelled by user"}
    assert "message" not in {f.event for f in rest}
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "cancelled"


async def test_a_run_waiting_at_a_gate_is_cancelled_and_its_gate_closed(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with worker(postgres_url, redis_url), api(postgres_url, redis_url) as client:
        run_id = await post_gated_run(client)
        paused = await until_waiting(client, run_id)
        response = await client.post(f"/runs/{run_id}/cancel")
        approve = await client.post(
            f"/runs/{run_id}/approvals", json={"node_id": "gate", "decision": "approve"}
        )
        rest = await collect(client, run_id, headers={"Last-Event-ID": str(paused[-1].id)})

    assert response.status_code == 202, response.text
    assert approve.status_code == 409
    assert [(f.event, f.data["payload"]) for f in rest] == [
        ("run_cancelled", {"reason": "cancelled by user"})
    ]
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "cancelled"


async def test_a_queued_run_is_cancelled_by_the_worker_that_claims_it(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        run_id = await post_slow_run(client)
        response = await client.post(f"/runs/{run_id}/cancel")
        async with worker(postgres_url, redis_url):
            frames = await collect(client, run_id)

    assert response.status_code == 202, response.text
    assert [f.event for f in frames] == ["run_started", "run_cancelled"]
    assert frames[-1].data["payload"] == {"reason": "cancelled by user"}
    run = await get_run(sessions, run_id)
    assert run is not None and run.status == "cancelled"


async def test_cancelling_an_unknown_or_ended_run_is_refused(
    postgres_url: str, redis_url: str
) -> None:
    async with worker(postgres_url, redis_url), api(postgres_url, redis_url) as client:
        unknown = await client.post(f"/runs/{uuid4()}/cancel")
        run_id = await post_slow_run(client)
        await collect(client, run_id)
        ended = await client.post(f"/runs/{run_id}/cancel")

    assert unknown.status_code == 404
    assert ended.status_code == 409
    assert "has already ended (completed)" in ended.text


# `POST /runs/{id}/rerun`: a new run linked to the one it repeats.


async def unqueue(redis_url: str, *run_ids: str) -> None:
    """Take runs off the queue: these tests have no worker, and the next test's worker must not
    pick them up."""
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        for run_id in run_ids:
            await redis.lrem(RUN_QUEUE, 0, run_id)  # pyright: ignore[reportUnknownMemberType]
    finally:
        await redis.aclose()


async def ended_run(
    sessions: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
    redis_url: str,
    body: dict[str, Any],
    status: str,
) -> str:
    """A run started with `body`, then set to `status` as a worker would have left it."""
    response = await client.post("/runs", json=body)
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    await unqueue(redis_url, run_id)
    async with sessions.begin() as session:
        await session.execute(
            update(Run)
            .where(Run.id == UUID(run_id))
            .values(status=status, failure_reason="boom" if status == "failed" else None)
        )
    return run_id


async def stored_row(sessions: async_sessionmaker[AsyncSession], run_id: str) -> Run:
    async with sessions() as session:
        row = await session.get(Run, UUID(run_id))
    assert row is not None
    return row


@pytest.mark.parametrize("status", ["failed", "cancelled", "completed"])
async def test_an_ended_run_is_rerun_as_a_new_linked_run(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, status: str
) -> None:
    async with github_connected(sessions), api(postgres_url, redis_url) as client:
        original_id = await ended_run(sessions, client, redis_url, DOCS_RUN, status)
        before = await stored_row(sessions, original_id)
        response = await client.post(f"/runs/{original_id}/rerun")
        assert response.status_code == 202, response.text
        new_id = response.json()["run_id"]
        # Other tests leave runs of their own in this database: list the docs runs only.
        listed = (await client.get("/runs", params={"template": "generate-docs"})).json()["items"]
        detail = (await client.get(f"/runs/{new_id}")).json()
    await unqueue(redis_url, new_id)

    original, rerun = await stored_row(sessions, original_id), await stored_row(sessions, new_id)
    assert new_id != original_id
    assert response.json()["events_url"].endswith(f"/runs/{new_id}/events")
    copied = ("spec", "input", "repo", "repo_url", "workspace_id", "template_id")
    assert {k: getattr(rerun, k) for k in copied} == {k: getattr(original, k) for k in copied}
    assert rerun.template_parameters == {"output_dir": "documentation"}
    assert (rerun.status, rerun.rerun_of, rerun.failure_reason) == ("queued", before.id, None)
    # The original is not changed.
    assert (original.status, original.updated_at, original.rerun_of) == (
        status,
        before.updated_at,
        None,
    )
    assert listed[0]["id"] == new_id and listed[0]["rerun_of"] == original_id
    assert detail["rerun_of"] == original_id


async def test_a_rerun_of_a_rerun_links_to_its_parent(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        first = await ended_run(
            sessions,
            client,
            redis_url,
            {"workflow": spec_json("valid/two-step-sequence.json")},
            "failed",
        )
        second = (await client.post(f"/runs/{first}/rerun")).json()["run_id"]
        await unqueue(redis_url, second)
        async with sessions.begin() as session:
            await session.execute(update(Run).where(Run.id == UUID(second)).values(status="failed"))
        third = (await client.post(f"/runs/{second}/rerun")).json()["run_id"]
    await unqueue(redis_url, third)

    assert (await stored_row(sessions, third)).rerun_of == UUID(second)
    assert (await stored_row(sessions, second)).rerun_of == UUID(first)


@pytest.mark.parametrize("status", ["queued", "running", "waiting"])
async def test_a_run_that_has_not_ended_is_not_rerun(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, status: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        run_id = await ended_run(
            sessions,
            client,
            redis_url,
            {"workflow": spec_json("valid/two-step-sequence.json")},
            status,
        )
        runs_before = await count_runs(sessions)
        response = await client.post(f"/runs/{run_id}/rerun")

    assert response.status_code == 409
    assert f"has not ended ({status})" in response.text
    assert await count_runs(sessions) == runs_before


async def test_rerunning_an_unknown_run_is_404(postgres_url: str, redis_url: str) -> None:
    async with api(postgres_url, redis_url) as client:
        response = await client.post(f"/runs/{uuid4()}/rerun")

    assert response.status_code == 404


async def test_a_publishing_run_is_not_rerun_once_github_is_disconnected(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        async with github_connected(sessions):
            run_id = await ended_run(sessions, client, redis_url, DOCS_RUN, "failed")
        runs_before = await count_runs(sessions)
        response = await client.post(f"/runs/{run_id}/rerun")

    assert response.status_code == 409
    assert "no GitHub connection" in response.text
    assert await count_runs(sessions) == runs_before


async def test_a_workflow_run_has_no_template_parameters(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str
) -> None:
    async with api(postgres_url, redis_url) as client:
        run_id = await ended_run(
            sessions,
            client,
            redis_url,
            {"workflow": spec_json("valid/two-step-sequence.json")},
            "completed",
        )

    row = await stored_row(sessions, run_id)
    assert (row.template_id, row.template_parameters) == (None, None)
