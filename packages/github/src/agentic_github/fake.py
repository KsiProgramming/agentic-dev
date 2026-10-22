"""A stand-in for the platform's GitHub App, for local dev and end-to-end tests
(`AGENTIC_GITHUB=fake`). It never calls GitHub.

It has one installation, on the `e2e-org` organisation, which reaches the repos in
`FAKE_REPOS`. Installing it sends the browser straight back to the API's setup URL. Their
clones and pushes go to bare repos under a local fixtures directory (`fixture_path`), and pull
requests are numbered in memory."""

import itertools
from pathlib import Path
from urllib.parse import urlencode

from pydantic import SecretStr

from agentic_github.errors import InstallationNotFoundError
from agentic_github.models import InstallationInfo, PullRequestInfo, RepoInfo

FAKE_INSTALLATION_ID = 1
FAKE_ACCOUNT = "e2e-org"
FAKE_REPOS = (
    RepoInfo(
        id=1001,
        full_name=f"{FAKE_ACCOUNT}/docs-demo",
        name="docs-demo",
        owner=FAKE_ACCOUNT,
        private=False,
        default_branch="main",
        html_url=f"https://github.com/{FAKE_ACCOUNT}/docs-demo",
    ),
    RepoInfo(
        id=1002,
        full_name=f"{FAKE_ACCOUNT}/private-lib",
        name="private-lib",
        owner=FAKE_ACCOUNT,
        private=True,
        default_branch="main",
        html_url=f"https://github.com/{FAKE_ACCOUNT}/private-lib",
    ),
)


def fixture_path(fixtures_root: Path, full_name: str) -> Path:
    """The bare repo standing in for `full_name` (`<root>/<owner>/<name>.git`)."""
    return fixtures_root / f"{full_name}.git"


class FakeGithubApp:
    """Has `GithubApp`'s interface. `api_base_url` is where the browser reaches the API, which
    the fake install flow sends it back to."""

    def __init__(self, api_base_url: str) -> None:
        self._api_base_url = api_base_url.rstrip("/")
        self._numbers = itertools.count(1)

    def install_url(self, state: str) -> str:
        query = urlencode(
            {"installation_id": FAKE_INSTALLATION_ID, "setup_action": "install", "state": state}
        )
        return f"{self._api_base_url}/github/setup?{query}"

    async def get_installation(self, installation_id: int) -> InstallationInfo:
        self._check(installation_id)
        return InstallationInfo(
            id=installation_id, account_login=FAKE_ACCOUNT, account_type="Organization"
        )

    async def list_repos(self, installation_id: int) -> list[RepoInfo]:
        self._check(installation_id)
        return list(FAKE_REPOS)

    async def installation_token(self, installation_id: int) -> SecretStr:
        self._check(installation_id)
        return SecretStr("fake-installation-token")

    async def open_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequestInfo:
        self._check(installation_id)
        number = next(self._numbers)
        return PullRequestInfo(
            number=number, url=f"https://github.com/{full_name}/pull/{number}", head=head, base=base
        )

    def close(self) -> None:
        pass

    @staticmethod
    def _check(installation_id: int) -> None:
        if installation_id != FAKE_INSTALLATION_ID:
            raise InstallationNotFoundError(installation_id)
