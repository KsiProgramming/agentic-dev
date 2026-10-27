"""`GET /runs` and `GET /runs/{id}`: run summaries, with status taken from the event log.

Each test lists the runs of its own workspace, so runs made by other tests do not show up.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.events import RunEvent, RunEventLog
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_sandbox import RepoSource
from agentic_store import PostgresEventSink, Workspace, create_run

pytestmark = pytest.mark.integration

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "two-step-sequence.json"
)
DOCS = RepoSource(url="https://github.com/acme/docs")
API = RepoSource(url="https://github.com/acme/api")


def two_step_spec() -> WorkflowSpec:
    return parse_spec(json.loads(SPEC.read_text(encoding="utf-8")))


@pytest.fixture
async def client(postgres_url: str, redis_url: str) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def workspace(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name="summaries"))
    return workspace_id


async def add_run(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    *events: tuple[str, dict[str, Any]],
    repo: RepoSource | None = None,
    template_id: str | None = None,
    input: str = "go",
) -> UUID:
    """A run of `workspace_id` with these events (type, payload) written through the sink."""
    run_id = await create_run(
        sessions, two_step_spec(), input, repo, workspace_id, template_id=template_id
    )
    log = RunEventLog(run_id, PostgresEventSink(sessions))
    for type, payload in events:
        node_id = "gate" if type == "gate_waiting" else None
        await log.emit(type, node_id=node_id, payload=payload)
    return run_id


type Events = tuple[tuple[str, dict[str, Any]], ...]

COMPLETED: Events = (("run_started", {}), ("run_completed", {}))
FAILED: Events = (("run_started", {}), ("run_failed", {"error": "RuntimeError: boom"}))
WAITING: Events = (("run_started", {}), ("gate_waiting", {"title": "Approve the notes"}))


async def list_runs(client: AsyncClient, workspace_id: UUID, **params: Any) -> dict[str, Any]:
    response = await client.get("/runs", params={"workspace_id": str(workspace_id), **params})
    assert response.status_code == 200, response.text
    return response.json()


def ids(page: dict[str, Any]) -> list[str]:
    return [item["id"] for item in page["items"]]


async def test_done_when_the_api_lists_past_runs_with_status_from_the_log(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    """Done when (2.3): the API lists past runs with status taken from the event log."""
    completed = await add_run(sessions, workspace, *COMPLETED, repo=DOCS)
    failed = await add_run(sessions, workspace, *FAILED)
    waiting = await add_run(sessions, workspace, *WAITING)
    queued = await add_run(sessions, workspace)

    page = await list_runs(client, workspace)

    assert ids(page) == [str(queued), str(waiting), str(failed), str(completed)]
    assert [item["status"] for item in page["items"]] == [
        "queued",
        "waiting",
        "failed",
        "completed",
    ]
    assert page["next_cursor"] is None
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[str(waiting)]["waiting_gate"] == {"node_id": "gate", "title": "Approve the notes"}
    done = by_id[str(completed)]
    assert done["repo"] == {"url": DOCS.url, "ref": None}
    assert done["workflow"] == {"id": two_step_spec().id, "name": two_step_spec().name}
    assert done["started_at"] is not None and done["finished_at"] is not None
    assert done["duration_ms"] >= 0
    assert by_id[str(queued)]["duration_ms"] is None
    assert done["active_ms"] >= 0 and done["waiting_ms"] == 0
    assert (by_id[str(queued)]["active_ms"], by_id[str(queued)]["waiting_ms"]) == (None, 0)
    # A waiting run's wait counts up to now; its active time stopped at the gate.
    assert by_id[str(waiting)]["waiting_ms"] >= 0
    assert by_id[str(waiting)]["active_ms"] is not None
    # The list does not carry the input or the failure reason; the detail does.
    assert "input" not in done and "failure_reason" not in done


async def test_pages_follow_the_cursor_without_gaps_or_duplicates(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    runs = [await add_run(sessions, workspace, *COMPLETED) for _ in range(7)]
    newest_first = [str(r) for r in reversed(runs)]

    seen: list[str] = []
    sizes: list[int] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        page = await list_runs(client, workspace, **params)
        seen += ids(page)
        sizes.append(len(page["items"]))
        if len(seen) == 3:
            # A run started between pages does not shift the next ones.
            await add_run(sessions, workspace)
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert sizes == [3, 3, 1]
    assert seen == newest_first


async def test_filters_by_status_template_and_repo(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    docs = await add_run(sessions, workspace, *COMPLETED, repo=DOCS, template_id="generate-docs")
    failed = await add_run(sessions, workspace, *FAILED, repo=API)
    cancelled_events: Events = (("run_started", {}), ("run_cancelled", {}))
    cancelled = await add_run(sessions, workspace, *cancelled_events, repo=API)
    waiting = await add_run(sessions, workspace, *WAITING)

    assert ids(await list_runs(client, workspace, status="waiting")) == [str(waiting)]
    assert ids(await list_runs(client, workspace, status=["failed", "cancelled"])) == [
        str(cancelled),
        str(failed),
    ]
    assert ids(await list_runs(client, workspace, template="generate-docs")) == [str(docs)]
    assert ids(await list_runs(client, workspace, repo=API.url)) == [str(cancelled), str(failed)]
    assert ids(await list_runs(client, workspace, repo=API.url, status="failed")) == [str(failed)]


async def test_runs_of_other_workspaces_are_not_listed(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    other = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=other, name="other"))
    await add_run(sessions, other, *COMPLETED)

    assert (await list_runs(client, workspace))["items"] == []
    unknown = await client.get("/runs", params={"workspace_id": str(uuid4())})
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"cursor": "not-a-cursor"},
        {"cursor": "W10"},  # base64 of `[]`
        {"limit": 0},
        {"limit": 101},
        {"status": "done"},
    ],
)
async def test_bad_list_parameters_are_refused(
    client: AsyncClient, workspace: UUID, params: dict[str, Any]
) -> None:
    response = await client.get("/runs", params={"workspace_id": str(workspace), **params})

    assert response.status_code == 422


async def test_a_runs_detail_has_its_input_and_failure_reason(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    run_id = await add_run(sessions, workspace, *FAILED, repo=API, input="write the docs")

    response = await client.get(f"/runs/{run_id}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["id"] == str(run_id)
    assert detail["status"] == "failed"
    assert detail["input"] == "write the docs"
    assert detail["failure_reason"] == "RuntimeError: boom"
    assert detail["workspace_id"] == str(workspace)
    assert detail["template_id"] is None
    assert detail["rerun_of"] is None
    assert detail["duration_ms"] >= 0
    assert WorkflowSpec.model_validate(detail["spec"]) == two_step_spec()


async def test_only_a_runs_detail_has_its_spec(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    await add_run(sessions, workspace, *COMPLETED)

    page = await list_runs(client, workspace)

    assert "spec" not in page["items"][0]


async def test_an_unknown_run_is_404(client: AsyncClient) -> None:
    response = await client.get(f"/runs/{uuid4()}")

    assert response.status_code == 404


async def test_a_runs_active_and_waiting_time_are_apart(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], workspace: UUID
) -> None:
    """Done when (11.2): a run that waited 1 h at a gate and worked 2 min reports both."""
    run_id = await create_run(sessions, two_step_spec(), "go", None, workspace)
    sink = PostgresEventSink(sessions)
    t0 = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    for seq, (type, seconds) in enumerate(
        (("run_started", 0), ("gate_waiting", 60), ("run_resumed", 3660), ("run_completed", 3720)),
        1,
    ):
        await sink.emit(
            RunEvent(
                run_id=run_id,
                seq=seq,
                type=type,
                node_id="gate" if type == "gate_waiting" else None,
                created_at=t0 + timedelta(seconds=seconds),
            )
        )

    detail = (await client.get(f"/runs/{run_id}")).json()
    item = (await list_runs(client, workspace))["items"][0]

    for run in (detail, item):
        assert (run["active_ms"], run["waiting_ms"]) == (120_000, 3_600_000)
        assert run["duration_ms"] == 3_720_000  # wall clock, deprecated
