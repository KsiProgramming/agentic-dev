import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_api.workspaces.claude_keys import KeyCheck
from agentic_secrets import generate_key_file
from agentic_store import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.integration

SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs"
CONNECTIONS = f"/workspaces/{DEFAULT_WORKSPACE_ID}/connections"


def spec_json(name: str) -> dict[str, Any]:
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


class StubVerifier:
    """Answers `result` for every key, and records the keys it was asked about."""

    def __init__(self) -> None:
        self.result: KeyCheck = "valid"
        self.keys: list[str] = []

    async def verify(self, key: SecretStr) -> KeyCheck:
        self.keys.append(key.get_secret_value())
        return self.result


@pytest.fixture
def verifier() -> StubVerifier:
    return StubVerifier()


async def client_for(
    settings: Settings, verifier: StubVerifier | None = None
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, claude_keys=verifier or StubVerifier())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def client(
    postgres_url: str,
    redis_url: str,
    tmp_path: Path,
    verifier: StubVerifier,
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)
    settings = Settings(database_url=postgres_url, redis_url=redis_url, master_key_file=master_key)
    async for c in client_for(settings, verifier):
        yield c
        # Leave the default workspace with no connection for the next test.
        await c.delete(f"{CONNECTIONS}/claude")


async def test_the_default_workspace_is_listed(client: AsyncClient) -> None:
    response = await client.get("/workspaces")

    assert response.status_code == 200
    assert {"id": str(DEFAULT_WORKSPACE_ID), "name": "Default"}.items() <= response.json()[
        0
    ].items()


async def test_a_workspace_is_created(client: AsyncClient) -> None:
    response = await client.post("/workspaces", json={"name": "E2E"})

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "E2E"
    assert created in (await client.get("/workspaces")).json()
    assert (await client.get(f"/workspaces/{created['id']}/connections")).json() == []
    assert (await client.post("/workspaces", json={"name": ""})).status_code == 422


async def test_a_stored_key_is_shown_by_its_hint_only(client: AsyncClient) -> None:
    key = f"sk-ant-api-test-{uuid4().hex}"

    put = await client.put(f"{CONNECTIONS}/claude", json={"api_key": f"  {key}\n"})
    listed = await client.get(CONNECTIONS)

    assert put.status_code == 200
    assert put.json()["key_hint"] == key[-4:]
    assert listed.status_code == 200
    assert [(c["provider"], c["key_hint"]) for c in listed.json()] == [("claude", key[-4:])]
    assert key not in put.text
    assert key not in listed.text


async def test_replacing_a_key_keeps_one_connection(client: AsyncClient) -> None:
    await client.put(f"{CONNECTIONS}/claude", json={"api_key": "sk-ant-first-1111"})
    await client.put(f"{CONNECTIONS}/claude", json={"api_key": "sk-ant-second-2222"})

    listed = (await client.get(CONNECTIONS)).json()

    assert [c["key_hint"] for c in listed] == ["2222"]


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": "sk-an"},
        {"api_key": "sk-ant-valid-but-extra-field", "note": "sk-ant-in-another-field"},
        {"key": "sk-ant-wrong-field-name"},
    ],
)
async def test_an_invalid_body_does_not_echo_the_key(
    client: AsyncClient, body: dict[str, str]
) -> None:
    response = await client.put(f"{CONNECTIONS}/claude", json=body)

    assert response.status_code == 422
    for value in body.values():
        assert value not in response.text


async def test_delete(client: AsyncClient) -> None:
    await client.put(f"{CONNECTIONS}/claude", json={"api_key": "sk-ant-delete-3333"})

    assert (await client.delete(f"{CONNECTIONS}/claude")).status_code == 204
    assert (await client.get(CONNECTIONS)).json() == []
    assert (await client.delete(f"{CONNECTIONS}/claude")).status_code == 404


async def test_an_unknown_workspace_is_404(client: AsyncClient) -> None:
    missing = f"/workspaces/{uuid4()}/connections"

    assert (await client.get(missing)).status_code == 404
    assert (
        await client.put(f"{missing}/claude", json={"api_key": "sk-ant-nowhere-4444"})
    ).status_code == 404
    assert (await client.delete(f"{missing}/claude")).status_code == 404
    run = await client.post(
        "/runs",
        json={"workflow": spec_json("valid/two-step-sequence.json"), "workspace_id": str(uuid4())},
    )
    assert run.status_code == 404


async def test_a_run_is_created_in_the_default_or_given_workspace(client: AsyncClient) -> None:
    spec = spec_json("valid/two-step-sequence.json")

    implicit = await client.post("/runs", json={"workflow": spec})
    explicit = await client.post(
        "/runs", json={"workflow": spec, "workspace_id": str(DEFAULT_WORKSPACE_ID)}
    )

    assert implicit.status_code == 202
    assert explicit.status_code == 202


async def test_without_a_master_key_keys_cannot_be_stored_but_runs_start(
    postgres_url: str, redis_url: str
) -> None:
    async for client in client_for(Settings(database_url=postgres_url, redis_url=redis_url)):
        put = await client.put(f"{CONNECTIONS}/claude", json={"api_key": "sk-ant-nokey-5555"})
        run = await client.post(
            "/runs", json={"workflow": spec_json("valid/two-step-sequence.json")}
        )

        assert put.status_code == 503
        assert "MASTER_KEY_FILE" in put.json()["detail"]
        assert "sk-ant-nokey-5555" not in put.text
        assert run.status_code == 202


async def test_a_key_is_checked_before_it_is_stored(
    client: AsyncClient, verifier: StubVerifier
) -> None:
    await client.put(f"{CONNECTIONS}/claude", json={"api_key": "  sk-ant-checked-1234\n"})

    assert verifier.keys == ["sk-ant-checked-1234"]


@pytest.mark.parametrize(
    ("result", "status", "code"),
    [("invalid", 422, "invalid_key"), ("unavailable", 502, "verify_unavailable")],
)
async def test_a_key_that_fails_its_check_is_not_stored(
    client: AsyncClient,
    verifier: StubVerifier,
    caplog: pytest.LogCaptureFixture,
    result: KeyCheck,
    status: int,
    code: str,
) -> None:
    key = f"sk-ant-refused-{uuid4().hex}"
    verifier.result = result

    response = await client.put(f"{CONNECTIONS}/claude", json={"api_key": key})

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert key not in response.text
    assert key not in caplog.text
    assert (await client.get(CONNECTIONS)).json() == []
