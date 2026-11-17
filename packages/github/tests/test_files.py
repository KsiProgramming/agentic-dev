"""Reading one file of a repo at a ref (7.7): a spec file a run is started from."""

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from pydantic import SecretStr

from agentic_github import (
    FAKE_ACCOUNT,
    FAKE_INSTALLATION_ID,
    FakeGithubApp,
    GithubApp,
    GithubAppConfig,
    NotAFileError,
)
from agentic_github.testing import private_key_pem, token_payload

API = "https://api.github.com"
INSTALLATION = 42
TOKEN = "ghs_installationtoken0007"
REPO = "acme/shop"
SPEC = "# CSV export\n\nAdmins download orders as CSV.\n"


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


def _file(path: str, text: str) -> dict[str, object]:
    return {
        "type": "file",
        "path": path,
        "size": len(text.encode()),
        "encoding": "base64",
        "content": base64.encodebytes(text.encode()).decode(),
    }


async def test_a_file_is_read_at_the_ref(app: GithubApp, mock: respx.MockRouter) -> None:
    route = mock.get(f"/repos/{REPO}/contents/docs/spec.md").respond(
        200, json=_file("docs/spec.md", SPEC)
    )

    found = await app.file_at(INSTALLATION, REPO, "docs/spec.md", "feature/x")

    assert found is not None
    assert (found.path, found.size, found.content) == ("docs/spec.md", len(SPEC), SPEC.encode())
    request = route.calls.last.request
    assert request.url.params["ref"] == "feature/x"
    assert request.headers["authorization"] == f"token {TOKEN}"


async def test_without_a_ref_the_default_branch_is_read(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    route = mock.get(f"/repos/{REPO}/contents/spec.md").respond(200, json=_file("spec.md", SPEC))

    await app.file_at(INSTALLATION, REPO, "spec.md")

    assert "ref" not in route.calls.last.request.url.params


async def test_a_missing_file_is_none(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.get(f"/repos/{REPO}/contents/nope.md").respond(404, json={"message": "Not Found"})

    assert await app.file_at(INSTALLATION, REPO, "nope.md", "main") is None


async def test_a_folder_or_a_submodule_is_not_a_file(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    mock.get(f"/repos/{REPO}/contents/docs").respond(200, json=[_file("docs/a.md", "a")])
    mock.get(f"/repos/{REPO}/contents/vendor").respond(
        200, json={"type": "submodule", "path": "vendor", "size": 0}
    )

    with pytest.raises(NotAFileError, match="folder"):
        await app.file_at(INSTALLATION, REPO, "docs")
    with pytest.raises(NotAFileError, match="submodule"):
        await app.file_at(INSTALLATION, REPO, "vendor")


async def test_a_file_too_large_to_be_sent_inline_has_no_content(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    mock.get(f"/repos/{REPO}/contents/big.md").respond(
        200,
        json={
            "type": "file",
            "path": "big.md",
            "size": 2_000_000,
            "encoding": "none",
            "content": "",
        },
    )

    found = await app.file_at(INSTALLATION, REPO, "big.md")

    assert found is not None
    assert (found.size, found.content) == (2_000_000, None)


async def test_the_fake_reads_files_put_in_it_and_its_bare_repos(tmp_path: Path) -> None:
    fake = FakeGithubApp("http://api", tmp_path)
    repo = f"{FAKE_ACCOUNT}/docs-demo"
    fake.files[(repo, "docs/spec.md")] = SPEC

    found = await fake.file_at(FAKE_INSTALLATION_ID, repo, "docs/spec.md", "main")

    assert found is not None and found.content == SPEC.encode()
    with pytest.raises(NotAFileError):
        await fake.file_at(FAKE_INSTALLATION_ID, repo, "docs")
    assert await fake.file_at(FAKE_INSTALLATION_ID, repo, "missing.md") is None
    created = await fake.create_org_repo(
        FAKE_INSTALLATION_ID, FAKE_ACCOUNT, "new-one", private=False
    )
    readme = await fake.file_at(FAKE_INSTALLATION_ID, created.full_name, "README.md")
    assert readme is not None and readme.content == b"# new-one\n"
