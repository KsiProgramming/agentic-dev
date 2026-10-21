import io
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import jwt
import pytest
import respx
from pydantic import SecretStr

from agentic_github import (
    GithubApiError,
    GithubApp,
    GithubAppConfig,
    GithubConfigError,
    InstallationInfo,
    InstallationNotFoundError,
    RepoInfo,
)
from agentic_github.testing import (
    installation_payload,
    private_key_pem,
    repo_payload,
    repos_page,
    token_payload,
)
from agentic_secrets import REDACTED, install_redaction

API = "https://api.github.com"
APP_ID = 1234
INSTALLATION = 42
TOKEN = "ghs_installationtoken0001"


@pytest.fixture(scope="module")
def pem() -> str:
    return private_key_pem()


@pytest.fixture
def app(pem: str) -> Iterator[GithubApp]:
    github = GithubApp(
        GithubAppConfig(app_id=APP_ID, slug="agentic-dev", private_key=SecretStr(pem)),
        auto_retry=False,
    )
    yield github
    github.close()


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


def _mock_token(mock: respx.MockRouter) -> respx.Route:
    return mock.post(f"/app/installations/{INSTALLATION}/access_tokens").respond(
        201, json=token_payload(TOKEN)
    )


async def test_get_installation_is_signed_with_the_app_jwt(
    app: GithubApp, mock: respx.MockRouter, pem: str
) -> None:
    route = mock.get(f"/app/installations/{INSTALLATION}").respond(
        200, json=installation_payload(INSTALLATION, "acme")
    )

    info = await app.get_installation(INSTALLATION)

    assert info == InstallationInfo(
        id=INSTALLATION, account_login="acme", account_type="Organization"
    )
    scheme, token = route.calls.last.request.headers["authorization"].split(" ")
    assert scheme == "Bearer"
    public_key = jwt.get_unverified_header(token)  # an RS256 JWT
    assert public_key["alg"] == "RS256"
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == str(APP_ID)


async def test_list_repos_uses_an_installation_token_and_reuses_it(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    token = _mock_token(mock)
    repos = mock.get("/installation/repositories").respond(
        200, json=repos_page([repo_payload(7, "acme/api", private=True, default_branch="trunk")])
    )

    first = await app.list_repos(INSTALLATION)
    second = await app.list_repos(INSTALLATION)

    assert (
        first
        == second
        == [
            RepoInfo(
                id=7,
                full_name="acme/api",
                name="api",
                owner="acme",
                private=True,
                default_branch="trunk",
                html_url="https://github.com/acme/api",
            )
        ]
    )
    assert token.call_count == 1
    assert repos.calls.last.request.headers["authorization"] == f"token {TOKEN}"


async def test_list_repos_follows_pagination(app: GithubApp, mock: respx.MockRouter) -> None:
    _mock_token(mock)
    page_two = f"{API}/installation/repositories?per_page=100&page=2"
    mock.get("/installation/repositories", params={"page": "2"}).respond(
        200, json=repos_page([repo_payload(2, "acme/web")], total_count=2)
    )
    mock.get("/installation/repositories").respond(
        200,
        json=repos_page([repo_payload(1, "acme/api")], total_count=2),
        headers={"link": f'<{page_two}>; rel="next", <{page_two}>; rel="last"'},
    )

    repos = await app.list_repos(INSTALLATION)

    assert [r.full_name for r in repos] == ["acme/api", "acme/web"]


async def test_an_unknown_installation_is_not_found(app: GithubApp, mock: respx.MockRouter) -> None:
    not_found = {"message": "Not Found", "documentation_url": "https://docs.github.com"}
    mock.get(f"/app/installations/{INSTALLATION}").respond(404, json=not_found)
    mock.post(f"/app/installations/{INSTALLATION}/access_tokens").respond(404, json=not_found)

    with pytest.raises(InstallationNotFoundError):
        await app.get_installation(INSTALLATION)
    with pytest.raises(InstallationNotFoundError):
        await app.list_repos(INSTALLATION)


@pytest.mark.parametrize("status", [403, 500])
async def test_other_errors_carry_no_token(
    app: GithubApp, mock: respx.MockRouter, status: int
) -> None:
    _mock_token(mock)
    mock.get("/installation/repositories").respond(
        status, json={"message": "nope", "documentation_url": "https://docs.github.com"}
    )

    with pytest.raises(GithubApiError) as caught:
        await app.list_repos(INSTALLATION)

    assert str(caught.value) == f"GitHub returned {status}"
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__


async def test_an_unreachable_github_is_an_api_error(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    mock.get(f"/app/installations/{INSTALLATION}").mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(GithubApiError, match="RequestError"):
        await app.get_installation(INSTALLATION)


def test_the_private_key_is_redacted_while_the_app_is_open(pem: str) -> None:
    out = io.StringIO()
    logger = logging.getLogger("github-redact-test")
    handler = logging.StreamHandler(out)
    logger.addHandler(handler)
    logger.propagate = False
    install_redaction(logger)
    try:
        app = GithubApp(GithubAppConfig(app_id=APP_ID, slug="s", private_key=SecretStr(pem)))
        logger.warning("key: %s", pem)
        app.close()
        logger.warning("closed")
    finally:
        logger.removeHandler(handler)

    assert pem not in out.getvalue()
    assert REDACTED in out.getvalue()


def test_install_url_carries_the_slug_and_state(app: GithubApp) -> None:
    assert (
        app.install_url("abc") == "https://github.com/apps/agentic-dev/installations/new?state=abc"
    )


def test_config_reads_a_pem_file(tmp_path: Path, pem: str) -> None:
    path = tmp_path / "app.pem"
    path.write_text(pem, encoding="ascii")

    config = GithubAppConfig.from_file(APP_ID, "agentic-dev", path)

    assert config.private_key.get_secret_value() == pem


@pytest.mark.parametrize("content", [None, "not a key"])
def test_config_rejects_a_missing_or_bad_file(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "app.pem"
    if content is not None:
        path.write_text(content, encoding="ascii")

    with pytest.raises(GithubConfigError) as caught:
        GithubAppConfig.from_file(APP_ID, "agentic-dev", path)

    assert "not a key" not in str(caught.value)
