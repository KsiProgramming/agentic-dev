"""Done when (phase 1.4): a Claude key is stored encrypted, used by a run, and never appears in
logs. A canary key goes in through the API, a run on the Claude runtime uses it, and a second run
gets an API error that echoes the key back. The canary (also base64 and hex) must then appear in
none of: the logs at DEBUG, the run events, the API responses, the stored rows."""

import asyncio
import base64
import io
import json
import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.graph import checkpoint_serde
from agentic_engine.logging import JsonFormatter
from agentic_runtime.testing import MockClaude, error_reply, text_reply
from agentic_secrets import REDACTED, generate_key_file, install_redaction
from agentic_store import DEFAULT_WORKSPACE_ID, get_run, list_run_events
from agentic_worker.main import WorkerSettings, run

pytestmark = pytest.mark.integration

SPEC = Path(__file__).resolve().parents[2] / "engine/tests/fixtures/specs/valid/single-agent.json"
CANARY = f"sk-ant-canary-{uuid4().hex}"


def leaked(haystack: str | bytes) -> list[str]:
    """The forms of the canary found in `haystack`."""
    raw = CANARY.encode()
    forms = {
        "plain": raw,
        "base64": base64.b64encode(raw),
        "hex": raw.hex().encode(),
    }
    data = haystack.encode() if isinstance(haystack, str) else haystack
    return [name for name, form in forms.items() if form in data]


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    """Everything logged anywhere, at DEBUG, as the worker's JSON lines with redaction on."""
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


@pytest.fixture
async def api(
    postgres_url: str, redis_url: str, master_key: Path
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(database_url=postgres_url, redis_url=redis_url, master_key_file=master_key)
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
def master_key(tmp_path: Path) -> Path:
    path = tmp_path / "master.key"
    generate_key_file(path)
    return path


async def wait_until_ended(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> str:
    async with asyncio.timeout(10):
        while True:
            stored = await get_run(sessions, run_id)
            if stored is not None and stored.status in ("completed", "failed"):
                return stored.status
            await asyncio.sleep(0.05)


async def test_a_stored_key_is_used_by_runs_and_never_leaks(
    sessions: async_sessionmaker[AsyncSession],
    postgres_url: str,
    redis_url: str,
    master_key: Path,
    api: httpx.AsyncClient,
    logs: io.StringIO,
) -> None:
    responses: list[httpx.Response] = []
    connections = f"/workspaces/{DEFAULT_WORKSPACE_ID}/connections"

    responses.append(await api.put(f"{connections}/claude", json={"api_key": CANARY}))
    responses.append(await api.get(connections))
    assert responses[0].status_code == 200

    mock = MockClaude(
        [
            text_reply("All ", "good.", input_tokens=12, output_tokens=3),
            # The API echoing the key back, as a misbehaving provider or proxy might.
            error_reply(401, f"invalid x-api-key: {CANARY}", kind="authentication_error"),
        ]
    )
    stop, ready = asyncio.Event(), asyncio.Event()
    settings = WorkerSettings(
        database_url=postgres_url,
        redis_url=redis_url,
        queue_poll_s=0.1,
        runtime="claude",
        master_key_file=master_key,
    )
    worker = asyncio.create_task(
        run(
            settings,
            stop,
            ready,
            make_client=lambda key: mock.make_client(key.get_secret_value()),
            checkpointer=InMemorySaver(serde=checkpoint_serde()),
        )
    )
    try:
        async with asyncio.timeout(10):
            await ready.wait()
        workflow = json.loads(SPEC.read_text(encoding="utf-8"))
        run_ids: list[UUID] = []
        for _ in range(2):
            created = await api.post("/runs", json={"workflow": workflow, "input": "go"})
            responses.append(created)
            run_ids.append(UUID(created.json()["run_id"]))
            await wait_until_ended(sessions, run_ids[-1])
    finally:
        stop.set()
        async with asyncio.timeout(5):
            await worker

    # Used by the runs: both calls to Anthropic carried the stored key.
    assert mock.api_keys == [CANARY, CANARY]
    assert [(await get_run(sessions, r)) is not None for r in run_ids] == [True, True]
    ok, failed = [await list_run_events(sessions, r) for r in run_ids]
    assert ok[-1].type == "run_completed"
    assert failed[-1].type == "run_failed"
    # The echoed key reached the event log only as redacted text.
    failed_text = json.dumps([e.payload for e in failed])
    assert REDACTED in failed_text

    # Never anywhere else.
    events = json.dumps([e.model_dump(mode="json") for e in [*ok, *failed]])
    assert leaked(events) == []
    for response in responses:
        assert leaked(response.text) == [], response.request.url
    assert logs.getvalue(), "nothing was logged, so the log check proves nothing"
    assert leaked(logs.getvalue()) == []
    async with sessions() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT w.wrapped_dek, w.key_id, c.secret_nonce, c.secret_ciphertext,"
                    " c.key_hint"
                    " FROM workspaces w JOIN connections c ON c.workspace_id = w.id"
                    " WHERE w.id = :id"
                ),
                {"id": DEFAULT_WORKSPACE_ID},
            )
        ).all()
    assert len(rows) == 1
    for column in rows[0]:
        value = column if isinstance(column, bytes) else str(column).encode()
        assert leaked(value) == []
