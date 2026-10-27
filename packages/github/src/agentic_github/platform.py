"""What the API and the worker need from the platform's GitHub App: `GithubApp`, or
`FakeGithubApp` in local dev and end-to-end tests."""

from typing import Protocol

from pydantic import SecretStr

from agentic_github.models import InstallationInfo, PullRequestInfo, RepoInfo


class GithubPlatform(Protocol):
    def install_url(self, state: str) -> str: ...

    async def get_installation(self, installation_id: int) -> InstallationInfo: ...

    async def list_repos(self, installation_id: int) -> list[RepoInfo]: ...

    async def get_repo(self, installation_id: int, full_name: str) -> RepoInfo | None: ...

    async def create_org_repo(
        self,
        installation_id: int,
        org: str,
        name: str,
        *,
        private: bool,
        description: str | None = None,
        gitignore_template: str | None = None,
        license_template: str | None = None,
    ) -> RepoInfo: ...

    async def installation_token(self, installation_id: int) -> SecretStr: ...

    async def open_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequestInfo: ...

    def close(self) -> None: ...


def installation_settings_url(installation_id: int, account_login: str, account_type: str) -> str:
    """The installation's settings page on GitHub, where its owner picks the repos it reaches."""
    if account_type == "Organization":
        return f"https://github.com/organizations/{account_login}/settings/installations/{installation_id}"
    return f"https://github.com/settings/installations/{installation_id}"
