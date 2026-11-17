"""Runs given a Markdown spec file (7.7): `POST /runs` with `spec_file`, uploaded or read from the
repo through the GitHub App at the run's ref, kept on the run (`GET /runs/{id}`) and by its
rerun, and every refusal."""

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.templates import SddFileParams, build_sdd_file_spec
from agentic_github import FAKE_ACCOUNT, FAKE_INSTALLATION_ID, FakeGithubApp
from agentic_secrets import generate_key_file
from agentic_store import Run, put_github_connection

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
FULL_NAME = f"{FAKE_ACCOUNT}/docs-demo"
REPO_URL = f"https://github.com/{FULL_NAME}"
TEXT = "# CSV export\n\nAdmins download every order as CSV.\n"


@pytest.fixture
def github() -> FakeGithubApp:
    return FakeGithubApp("http://test")


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, tmp_path: Path, github: FakeGithubApp, sessions: Sessions
) -> AsyncIterator[AsyncClient]:
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        master_key_file=master_key,
        web_base_url="http://web.test/",
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        app.state.github = github
        yield c


@pytest.fixture
async def workspace(client: AsyncClient, sessions: Sessions) -> UUID:
    created = await client.post("/workspaces", json={"name": f"spec-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    workspace_id = UUID(created.json()["id"])
    await put_github_connection(sessions, workspace_id, FAKE_INSTALLATION_ID, FAKE_ACCOUNT)
    return workspace_id


def upload(name: str = "csv-export.md", content: str = TEXT) -> dict[str, Any]:
    return {"source": "upload", "name": name, "content": content}


async def start(
    client: AsyncClient,
    workspace: UUID,
    spec_file: dict[str, Any] | None,
    *,
    template: str = "sdd-spec-file",
    ref: str | None = None,
) -> Any:
    repo: dict[str, Any] = {"url": REPO_URL}
    if ref is not None:
        repo["ref"] = ref
    body: dict[str, Any] = {
        "workspace_id": str(workspace),
        "template": {"id": template},
        "repo": repo,
        "trigger": "manual",
    }
    if spec_file is not None:
        body["spec_file"] = spec_file
    return await client.post("/runs", json=body)


async def the_run(sessions: Sessions, run_id: str) -> Run:
    async with sessions() as session:
        run = await session.scalar(select(Run).where(Run.id == UUID(run_id)))
    assert run is not None
    return run


async def test_an_uploaded_spec_is_kept_on_the_run_and_named_by_its_input(
    client: AsyncClient, workspace: UUID, sessions: Sessions
) -> None:
    started = await start(client, workspace, upload())

    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    run = await the_run(sessions, run_id)
    assert run.input == "csv-export.md"
    assert run.spec_file == {
        "source": "upload",
        "name": "csv-export.md",
        "path": None,
        "ref": None,
        "size": len(TEXT.encode()),
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "text": TEXT,
    }
    detail = (await client.get(f"/runs/{run_id}")).json()
    assert detail["spec_file"] == {
        "source": "upload",
        "name": "csv-export.md",
        "path": None,
        "ref": None,
        "size": len(TEXT.encode()),
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    assert "text" not in detail["spec_file"]


async def test_a_spec_in_the_repo_is_read_at_the_runs_ref(
    client: AsyncClient, workspace: UUID, sessions: Sessions, github: FakeGithubApp
) -> None:
    github.files[(FULL_NAME, "docs/spec.md")] = TEXT

    started = await start(
        client, workspace, {"source": "repo", "path": "/docs/spec.md"}, ref="feature/x"
    )

    assert started.status_code == 202, started.text
    run = await the_run(sessions, started.json()["run_id"])
    assert run.input == "docs/spec.md"
    assert run.spec_file is not None
    assert (run.spec_file["path"], run.spec_file["name"], run.spec_file["ref"]) == (
        "docs/spec.md",
        "spec.md",
        "feature/x",
    )
    assert run.spec_file["text"] == TEXT


async def test_a_rerun_keeps_the_file_and_never_reads_the_repo_again(
    client: AsyncClient, workspace: UUID, sessions: Sessions, github: FakeGithubApp
) -> None:
    github.files[(FULL_NAME, "docs/spec.md")] = TEXT
    started = await start(client, workspace, {"source": "repo", "path": "docs/spec.md"})
    run_id = started.json()["run_id"]
    github.files[(FULL_NAME, "docs/spec.md")] = "# Changed since"
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == UUID(run_id)).values(status="failed"))

    rerun = await client.post(f"/runs/{run_id}/rerun")

    assert rerun.status_code == 202, rerun.text
    again = await the_run(sessions, rerun.json()["run_id"])
    assert again.spec_file is not None and again.spec_file["text"] == TEXT
    assert again.input == "docs/spec.md"


@pytest.mark.parametrize(
    ("spec_file", "code"),
    [
        (None, "spec_file_required"),
        (upload(name="spec.txt"), "spec_file_invalid"),
        (upload(name="docs/spec.md"), "spec_file_invalid"),
        (upload(content="  \n"), "spec_file_invalid"),
        (upload(content="x" * (256 * 1024 + 1)), "spec_file_invalid"),
        ({"source": "repo", "path": "../secrets.md"}, "path_invalid"),
        ({"source": "repo", "path": ".git/config.md"}, "path_invalid"),
        ({"source": "repo", "path": "docs/missing.md"}, "path_not_found"),
        ({"source": "repo", "path": "docs"}, "not_a_file"),
        ({"source": "repo", "path": "docs/notes.txt"}, "spec_file_invalid"),
    ],
)
async def test_a_bad_or_missing_file_is_refused(
    client: AsyncClient,
    workspace: UUID,
    sessions: Sessions,
    github: FakeGithubApp,
    spec_file: dict[str, Any] | None,
    code: str,
) -> None:
    github.files[(FULL_NAME, "docs/spec.md")] = TEXT
    github.files[(FULL_NAME, "docs/notes.txt")] = TEXT

    refused = await start(client, workspace, spec_file)

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"].startswith(f"{code}: "), refused.text


async def test_another_workflow_does_not_take_a_spec_file(
    client: AsyncClient, workspace: UUID
) -> None:
    refused = await start(client, workspace, upload(), template="generate-docs")

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"].startswith("spec_file_unexpected: ")


async def test_the_template_needs_no_jira_connection(client: AsyncClient, workspace: UUID) -> None:
    templates = (await client.get("/templates")).json()
    found = next(t for t in templates if t["id"] == "sdd-spec-file")

    assert found["requires"] == ["claude", "github"]
    assert build_sdd_file_spec(SddFileParams()).input is not None
