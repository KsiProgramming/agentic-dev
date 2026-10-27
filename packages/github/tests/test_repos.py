import asyncio
import json
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx
from pydantic import SecretStr

from agentic_github import (
    FAKE_ACCOUNT,
    FAKE_INSTALLATION_ID,
    FakeGithubApp,
    GithubApiError,
    GithubApp,
    GithubAppConfig,
    InstallationNotFoundError,
    RepoCreationNotAllowedError,
    RepoExistsError,
    fixture_path,
)
from agentic_github.testing import private_key_pem, repo_payload, token_payload

API = "https://api.github.com"
INSTALLATION = 42
TOKEN = "ghs_installationtoken0003"
ORG = "acme"


@pytest.fixture
def app() -> Iterator[GithubApp]:
    github = GithubApp(
        GithubAppConfig(app_id=1234, slug="agentic-dev", private_key=SecretStr(private_key_pem())),
        auto_retry=False,
    )
    yield github
    github.close()


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.post(f"/app/installations/{INSTALLATION}/access_tokens").respond(
            201, json=token_payload(TOKEN)
        )
        yield router


async def test_create_org_repo_asks_github_for_the_scaffold(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    route = mock.post(f"/orgs/{ORG}/repos").respond(
        201, json=repo_payload(9, f"{ORG}/docs-new", private=True)
    )

    repo = await app.create_org_repo(
        INSTALLATION,
        ORG,
        "docs-new",
        private=True,
        description="Docs demo",
        gitignore_template="Python",
        license_template="mit",
    )

    assert (repo.full_name, repo.private, repo.default_branch) == (f"{ORG}/docs-new", True, "main")
    assert repo.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    request = route.calls.last.request
    assert request.headers["authorization"] == f"token {TOKEN}"
    assert json.loads(request.content) == {
        "name": "docs-new",
        "private": True,
        "auto_init": True,
        "description": "Docs demo",
        "gitignore_template": "Python",
        "license_template": "mit",
    }


async def test_create_org_repo_leaves_out_unset_templates(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    route = mock.post(f"/orgs/{ORG}/repos").respond(201, json=repo_payload(9, f"{ORG}/bare"))

    await app.create_org_repo(INSTALLATION, ORG, "bare", private=False)

    assert json.loads(route.calls.last.request.content) == {
        "name": "bare",
        "private": False,
        "auto_init": True,
    }


async def test_a_taken_name_is_repo_exists(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.post(f"/orgs/{ORG}/repos").respond(
        422,
        json={
            "message": "Repository creation failed.",
            "errors": [
                {
                    "resource": "Repository",
                    "field": "name",
                    "code": "custom",
                    "message": "name already exists on this account",
                }
            ],
        },
    )

    with pytest.raises(RepoExistsError, match=f"{ORG}/taken"):
        await app.create_org_repo(INSTALLATION, ORG, "taken", private=True)


async def test_other_refusals_say_why(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.post(f"/orgs/{ORG}/repos").respond(
        422, json={"message": "Repository creation failed.", "errors": [{"message": "bad name"}]}
    )

    with pytest.raises(GithubApiError, match="bad name"):
        await app.create_org_repo(INSTALLATION, ORG, "x", private=True)


async def test_a_forbidden_creation_carries_no_token(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    mock.post(f"/orgs/{ORG}/repos").respond(
        403, json={"message": "Resource not accessible by integration"}
    )

    with pytest.raises(RepoCreationNotAllowedError) as caught:
        await app.create_org_repo(INSTALLATION, ORG, "x", private=True)

    assert "not accessible" in str(caught.value)
    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None


async def test_create_with_an_unknown_installation(app: GithubApp) -> None:
    with respx.mock(base_url=API) as router:
        router.post(f"/app/installations/{INSTALLATION}/access_tokens").respond(
            404, json={"message": "Not Found"}
        )
        with pytest.raises(InstallationNotFoundError):
            await app.create_org_repo(INSTALLATION, ORG, "x", private=True)


async def test_get_repo(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.get(f"/repos/{ORG}/api").respond(200, json=repo_payload(3, f"{ORG}/api", private=True))

    repo = await app.get_repo(INSTALLATION, f"{ORG}/api")

    assert repo is not None
    assert (repo.id, repo.full_name, repo.owner, repo.private) == (3, f"{ORG}/api", ORG, True)


async def test_get_repo_is_none_when_missing(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.get(f"/repos/{ORG}/nope").respond(404, json={"message": "Not Found"})

    assert await app.get_repo(INSTALLATION, f"{ORG}/nope") is None


async def test_get_repo_with_an_unknown_installation(app: GithubApp) -> None:
    with respx.mock(base_url=API) as router:
        router.post(f"/app/installations/{INSTALLATION}/access_tokens").respond(
            404, json={"message": "Not Found"}
        )
        with pytest.raises(InstallationNotFoundError):
            await app.get_repo(INSTALLATION, f"{ORG}/api")


# The fake.


async def test_the_fake_creates_a_bare_repo_with_one_scaffold_commit(tmp_path: Path) -> None:
    github = FakeGithubApp("", fixtures_root=tmp_path)
    before = datetime.now(UTC)

    repo = await github.create_org_repo(
        FAKE_INSTALLATION_ID,
        FAKE_ACCOUNT,
        "fresh",
        private=True,
        description="A new repo",
        gitignore_template="Python",
        license_template="mit",
    )

    assert (repo.full_name, repo.private, repo.default_branch) == (
        f"{FAKE_ACCOUNT}/fresh",
        True,
        "main",
    )
    assert repo.created_at is not None and repo.created_at >= before
    clone = tmp_path / "clone"
    bare = fixture_path(tmp_path, repo.full_name)
    log = await asyncio.to_thread(_clone_log, bare, clone)
    assert log == ["Initial commit"]
    assert sorted(p.name for p in clone.iterdir() if p.name != ".git") == [
        ".gitignore",
        "LICENSE",
        "README.md",
    ]
    assert "A new repo" in (clone / "README.md").read_text()


async def test_the_fake_sees_repos_another_instance_created(tmp_path: Path) -> None:
    await FakeGithubApp("", fixtures_root=tmp_path).create_org_repo(
        FAKE_INSTALLATION_ID, FAKE_ACCOUNT, "shared", private=False
    )
    other = FakeGithubApp("", fixtures_root=tmp_path)

    found = await other.get_repo(FAKE_INSTALLATION_ID, f"{FAKE_ACCOUNT}/shared")

    assert found is not None and not found.private
    names = [r.full_name for r in await other.list_repos(FAKE_INSTALLATION_ID)]
    assert f"{FAKE_ACCOUNT}/shared" in names
    with pytest.raises(RepoExistsError):
        await other.create_org_repo(FAKE_INSTALLATION_ID, FAKE_ACCOUNT, "shared", private=True)


async def test_the_fake_knows_its_fixed_repos_and_nothing_else(tmp_path: Path) -> None:
    github = FakeGithubApp("", fixtures_root=tmp_path)

    assert await github.get_repo(FAKE_INSTALLATION_ID, f"{FAKE_ACCOUNT}/docs-demo") is not None
    assert await github.get_repo(FAKE_INSTALLATION_ID, f"{FAKE_ACCOUNT}/missing") is None
    # A seeded fixture (no marks) is not a created repo.
    fixture_path(tmp_path, f"{FAKE_ACCOUNT}/seeded").mkdir(parents=True)
    assert await github.get_repo(FAKE_INSTALLATION_ID, f"{FAKE_ACCOUNT}/seeded") is None


async def test_the_fake_creates_repos_only_with_a_fixtures_root() -> None:
    with pytest.raises(RuntimeError, match="fixtures root"):
        await FakeGithubApp("").create_org_repo(
            FAKE_INSTALLATION_ID, FAKE_ACCOUNT, "x", private=True
        )


def _clone_log(bare: Path, clone: Path) -> list[str]:
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    log = subprocess.run(
        ["git", "-C", str(clone), "log", "--format=%s"], capture_output=True, text=True, check=True
    )
    return log.stdout.splitlines()
