"""The platform's GitHub App, through `githubkit`.

Calls about the App itself (`get_installation`) are signed with a JWT made from the private key.
Calls about an installation's repos use an installation token, which githubkit fetches with the
JWT and caches until a minute before it expires. Errors never carry the token or the headers."""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from typing import Protocol

from githubkit import AppAuthStrategy, GitHub
from githubkit.cache import MemCacheStrategy
from githubkit.exception import GitHubException, RequestFailed

from agentic_github.config import GithubAppConfig
from agentic_github.errors import GithubApiError, InstallationNotFoundError
from agentic_github.models import InstallationInfo, RepoInfo
from agentic_secrets import registered

GITHUB_API_URL = "https://api.github.com/"
_PER_PAGE = 100


class GithubApp:
    """One per process. The private key is redacted from logs until `close`."""

    def __init__(
        self, config: GithubAppConfig, *, base_url: str = GITHUB_API_URL, auto_retry: bool = True
    ) -> None:
        self.config = config
        self._redaction = ExitStack()
        self._redaction.enter_context(registered(config.private_key))
        self._github = GitHub(
            AppAuthStrategy(config.app_id, config.private_key.get_secret_value()),
            base_url=base_url,
            # Our own token and JWT cache, not githubkit's process-wide default.
            cache_strategy=MemCacheStrategy(),
            # Repo lists must be current; GitHub's ETags would serve stale pages.
            http_cache=False,
            auto_retry=auto_retry,
        )

    def install_url(self, state: str) -> str:
        return f"https://github.com/apps/{self.config.slug}/installations/new?state={state}"

    async def get_installation(self, installation_id: int) -> InstallationInfo:
        with _github_errors(installation_id):
            response = await self._github.rest.apps.async_get_installation(installation_id)
        installation = response.parsed_data
        # A user or an organisation has a login; an enterprise has a slug.
        account = installation.account
        login = getattr(account, "login", None) or getattr(account, "slug", "")
        return InstallationInfo(
            id=installation.id, account_login=str(login), account_type=installation.target_type
        )

    async def list_repos(self, installation_id: int) -> list[RepoInfo]:
        """Every repo the installation can reach, in GitHub's order."""
        auth = self._github.auth
        assert isinstance(auth, AppAuthStrategy)
        github = self._github.with_auth(auth.as_installation(installation_id))
        with _github_errors(installation_id):
            return [
                _repo_info(repo)
                async for repo in github.rest.paginate(
                    github.rest.apps.async_list_repos_accessible_to_installation,
                    map_func=lambda r: r.parsed_data.repositories,
                    per_page=_PER_PAGE,
                )
            ]

    def close(self) -> None:
        self._redaction.close()


@contextmanager
def _github_errors(installation_id: int) -> Generator[None]:
    """Maps githubkit errors to ours. `from None` drops the original, whose request and response
    hold the Authorization header."""
    try:
        yield
    except GitHubException as exc:
        # A failed installation token request surfaces wrapped in a `RequestError`.
        failed = exc if isinstance(exc, RequestFailed) else exc.__cause__
        if not isinstance(failed, RequestFailed):
            raise GithubApiError(f"GitHub request failed: {type(exc).__name__}") from None
        status = failed.response.status_code
        if status == 404:
            raise InstallationNotFoundError(installation_id) from None
        raise GithubApiError(f"GitHub returned {status}") from None


class _Owner(Protocol):
    @property
    def login(self) -> str: ...


class _Repo(Protocol):
    """The fields we read from githubkit's repository models, whatever the schema version."""

    @property
    def id(self) -> int: ...
    @property
    def full_name(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def owner(self) -> _Owner | None: ...
    @property
    def private(self) -> bool: ...
    @property
    def default_branch(self) -> str: ...
    @property
    def html_url(self) -> str: ...


def _repo_info(repo: _Repo) -> RepoInfo:
    return RepoInfo(
        id=repo.id,
        full_name=repo.full_name,
        name=repo.name,
        owner=repo.owner.login if repo.owner else repo.full_name.split("/", 1)[0],
        private=repo.private,
        default_branch=repo.default_branch,
        html_url=repo.html_url,
    )
