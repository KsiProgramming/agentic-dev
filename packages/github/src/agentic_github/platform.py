"""What the API and the worker need from the platform's GitHub App: `GithubApp`, or
`FakeGithubApp` in local dev and end-to-end tests."""

from typing import Protocol

from pydantic import SecretStr

from agentic_github.models import (
    InstallationInfo,
    PullRequestInfo,
    PullRequestState,
    RepoInfo,
    ReviewItem,
)
from agentic_github.webhooks import ReviewKind


class GithubReviews(Protocol):
    """What a follow-up on a pull request review needs (7.6): who may ask, the pull request's
    state, its comments, and the platform's two short answers (a reaction, one comment)."""

    async def repo_permission(self, installation_id: int, full_name: str, login: str) -> str:
        """`admin`, `maintain`, `write`, `triage`, `read` or `none`."""
        ...

    async def pull_request(
        self, installation_id: int, full_name: str, number: int
    ) -> PullRequestState | None: ...

    async def review_items(
        self, installation_id: int, full_name: str, number: int
    ) -> list[ReviewItem]: ...

    async def add_reaction(
        self, installation_id: int, full_name: str, kind: ReviewKind, comment_id: int, content: str
    ) -> bool: ...

    async def comment_on_pull_request(
        self, installation_id: int, full_name: str, number: int, body: str
    ) -> None: ...


class GithubPlatform(GithubReviews, Protocol):
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
