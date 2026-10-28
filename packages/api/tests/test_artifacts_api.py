"""`GET /runs/{id}/artifacts`: a run's artifacts, each version's content, and a download (4.3)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.spec import parse_spec
from agentic_store import PostgresArtifactStore, create_run

pytestmark = pytest.mark.integration

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "artifacts-findings.json"
)


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    app = create_app(Settings(database_url=postgres_url, redis_url=redis_url))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def run_id(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    """A run that wrote `findings.json` twice and `report.md` once."""
    spec = parse_spec(json.loads(SPEC.read_text(encoding="utf-8")))
    run_id = await create_run(sessions, spec, "go")
    store = PostgresArtifactStore(sessions, run_id)
    await store.put("findings.json", "scan", '{"findings": []}')
    await store.put("findings.json", "scan", '{"findings": [1]}')
    await store.put("report.md", "report", "# Report\n\n<script>alert(1)</script>")
    return run_id


async def test_the_list_has_the_latest_version_of_each(client: AsyncClient, run_id: UUID) -> None:
    response = await client.get(f"/runs/{run_id}/artifacts")

    assert response.status_code == 200, response.text
    listed = [(a["name"], a["version"], a["versions"], a["node_id"]) for a in response.json()]
    assert listed == [("findings.json", 2, 2, "scan"), ("report.md", 1, 1, "report")]
    assert response.json()[0]["media_type"] == "application/json"
    assert "content" not in response.json()[0]


async def test_one_version_with_its_content(client: AsyncClient, run_id: UUID) -> None:
    latest = await client.get(f"/runs/{run_id}/artifacts/findings.json")
    first = await client.get(f"/runs/{run_id}/artifacts/findings.json", params={"version": 1})

    assert latest.status_code == 200, latest.text
    assert (latest.json()["version"], latest.json()["content"]) == (2, '{"findings": [1]}')
    assert (first.json()["version"], first.json()["versions"]) == (1, 2)
    assert first.json()["content"] == '{"findings": []}'


async def test_unknown_runs_names_and_versions_are_404_and_bad_names_422(
    client: AsyncClient, run_id: UUID
) -> None:
    no_run = await client.get(f"/runs/{uuid4()}/artifacts")
    no_name = await client.get(f"/runs/{run_id}/artifacts/nope.json")
    no_version = await client.get(f"/runs/{run_id}/artifacts/report.md", params={"version": 2})
    bad = await client.get(f"/runs/{run_id}/artifacts/report.html")

    assert [r.status_code for r in (no_run, no_name, no_version, bad)] == [404, 404, 404, 422]
    assert no_version.json()["detail"] == "the run has no version 2 of artifact 'report.md'"


async def test_a_download_is_an_attachment_that_is_never_sniffed(
    client: AsyncClient, run_id: UUID
) -> None:
    response = await client.get(f"/runs/{run_id}/artifacts/report.md/download")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="report.md"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.text == "# Report\n\n<script>alert(1)</script>"
