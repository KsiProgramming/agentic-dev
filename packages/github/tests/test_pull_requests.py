import json
from collections.abc import Iterator

import pytest
import respx
from pydantic import SecretStr

from agentic_github import (
    GithubApiError,
    GithubApp,
    GithubAppConfig,
    InstallationNotFoundError,
    PullRequestError,
    PullRequestInfo,
)
from agentic_github.testing import private_key_pem, pull_payload, token_payload

API = "https://api.github.com"
INSTALLATION = 42
TOKEN = "ghs_installationtoken0002"
REPO = "acme/api"
HEAD = "agent/run/writer"


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


async def _open(app: GithubApp) -> PullRequestInfo:
    return await app.open_pull_request(
        INSTALLATION, REPO, head=HEAD, base="main", title="Add docs", body="Written by agents."
    )


async def test_installation_token_is_fresh_and_secret(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    token = await app.installation_token(INSTALLATION)

    assert isinstance(token, SecretStr)
    assert token.get_secret_value() == TOKEN
    assert TOKEN not in repr(token)


async def test_installation_token_of_an_unknown_installation(app: GithubApp) -> None:
    with respx.mock(base_url=API) as router:
        router.post(f"/app/installations/{INSTALLATION}/access_tokens").respond(
            404, json={"message": "Not Found"}
        )
        with pytest.raises(InstallationNotFoundError):
            await app.installation_token(INSTALLATION)


async def test_open_pull_request(app: GithubApp, mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/pulls").respond(201, json=pull_payload(7, REPO, head=HEAD))

    pull = await _open(app)

    assert pull == PullRequestInfo(
        number=7, url=f"https://github.com/{REPO}/pull/7", head=HEAD, base="main"
    )
    request = route.calls.last.request
    assert request.headers["authorization"] == f"token {TOKEN}"
    assert json.loads(request.content) == {
        "title": "Add docs",
        "head": HEAD,
        "base": "main",
        "body": "Written by agents.",
    }


async def test_an_open_pull_request_from_the_branch_is_reused(
    app: GithubApp, mock: respx.MockRouter
) -> None:
    mock.post(f"/repos/{REPO}/pulls").respond(
        422,
        json={
            "message": "Validation Failed",
            "errors": [{"message": f"A pull request already exists for acme:{HEAD}."}],
        },
    )
    listed = mock.get(f"/repos/{REPO}/pulls").respond(200, json=[pull_payload(3, REPO, head=HEAD)])

    pull = await _open(app)

    assert pull.number == 3
    assert listed.calls.last.request.url.params["head"] == f"acme:{HEAD}"
    assert listed.calls.last.request.url.params["state"] == "open"


async def test_a_refused_pull_request_says_why(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.post(f"/repos/{REPO}/pulls").respond(
        422,
        json={
            "message": "Validation Failed",
            "errors": [{"message": f"No commits between main and {HEAD}"}],
        },
    )
    mock.get(f"/repos/{REPO}/pulls").respond(200, json=[])

    with pytest.raises(PullRequestError, match="No commits between main"):
        await _open(app)


async def test_an_unreachable_repo_is_an_api_error(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.post(f"/repos/{REPO}/pulls").respond(404, json={"message": "Not Found"})

    with pytest.raises(GithubApiError, match="repo acme/api not found") as caught:
        await _open(app)

    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None


async def test_a_server_error_carries_no_token(app: GithubApp, mock: respx.MockRouter) -> None:
    mock.post(f"/repos/{REPO}/pulls").respond(502, json={"message": "Bad gateway"})

    with pytest.raises(GithubApiError) as caught:
        await _open(app)

    assert str(caught.value) == "GitHub returned 502"
