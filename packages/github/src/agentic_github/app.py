"""The platform's GitHub App, through `githubkit`.

Calls about the App itself (`get_installation`, `installation_token`) are signed with a JWT made
from the private key. Calls about an installation's repos (listing, reading and creating them,
opening pull requests) use an installation token, which githubkit fetches with the JWT and caches
until a minute before it expires. Errors never carry the token or the headers."""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from datetime import datetime
from typing import Any, Protocol, cast

from githubkit import AppAuthStrategy, GitHub
from githubkit.cache import MemCacheStrategy
from githubkit.exception import GitHubException, RequestFailed
from pydantic import SecretStr

from agentic_github.config import GithubAppConfig
from agentic_github.errors import (
    GithubApiError,
    InstallationNotFoundError,
    PullRequestError,
    RepoCreationNotAllowedError,
    RepoExistsError,
)
from agentic_github.models import InstallationInfo, PullRequestInfo, RepoInfo
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
        github = self._installation(installation_id)
        with _github_errors(installation_id):
            return [
                _repo_info(repo)
                async for repo in github.rest.paginate(
                    github.rest.apps.async_list_repos_accessible_to_installation,
                    map_func=lambda r: r.parsed_data.repositories,
                    per_page=_PER_PAGE,
                )
            ]

    async def installation_token(self, installation_id: int) -> SecretStr:
        """A fresh token for the installation (valid for an hour), for git over https. The
        caller registers it for redaction while it holds it."""
        with _github_errors(installation_id):
            response = await self._github.rest.apps.async_create_installation_access_token(
                installation_id
            )
        return SecretStr(response.parsed_data.token)

    async def open_pull_request(
        self, installation_id: int, full_name: str, *, head: str, base: str, title: str, body: str
    ) -> PullRequestInfo:
        """Open a pull request from `head` into `base` on `full_name`. If one is already open
        from `head` (a retried node), that one is returned. Raises `PullRequestError` if GitHub
        refuses it, `GithubApiError` if the repo cannot be reached."""
        owner, repo = full_name.split("/", 1)
        github = self._installation(installation_id)
        try:
            with _github_errors(installation_id, not_found=f"repo {full_name} not found"):
                response = await github.rest.pulls.async_create(
                    owner, repo, data={"title": title, "head": head, "base": base, "body": body}
                )
        except _Unprocessable as e:
            existing = await self._open_pull_request(github, installation_id, owner, repo, head)
            if existing is not None:
                return existing
            raise PullRequestError(f"GitHub refused the pull request: {e.reason}") from None
        return _pull_request_info(response.json())

    async def get_repo(self, installation_id: int, full_name: str) -> RepoInfo | None:
        """`full_name` as the installation sees it, or `None` if it does not exist or the
        installation cannot reach it."""
        owner, repo = full_name.split("/", 1)
        github = self._installation(installation_id)
        with _github_errors(installation_id, not_found=f"repo {full_name} not found"):
            try:
                response = await github.rest.repos.async_get(owner, repo)
            except RequestFailed as e:
                # Raised by the call itself: a failed token request comes wrapped.
                if e.response.status_code == 404:
                    return None
                raise
        return _full_repo_info(response.json())

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
    ) -> RepoInfo:
        """Create `org/name` with one scaffold commit made by GitHub: a README, plus the
        `.gitignore` and license templates if given. Raises `RepoExistsError` if the name is
        taken, `RepoCreationNotAllowedError` if the App or the organisation forbids it.
        (Installation tokens cannot create repos on a personal account.)"""
        data: dict[str, Any] = {"name": name, "private": private, "auto_init": True}
        if description:
            data["description"] = description
        if gitignore_template:
            data["gitignore_template"] = gitignore_template
        if license_template:
            data["license_template"] = license_template
        github = self._installation(installation_id)
        try:
            with _github_errors(
                installation_id,
                not_found=f"organisation {org} not found",
                forbidden=f"GitHub does not let the App create repos in {org}",
            ):
                response = await github.rest.repos.async_create_in_org(
                    org,
                    # githubkit's TypedDict, built key by key.
                    data=cast(Any, data),
                )
        except _Unprocessable as e:
            if "already exists" in e.reason:
                raise RepoExistsError(f"repo {org}/{name} already exists") from None
            raise GithubApiError(f"GitHub refused the repo: {e.reason}") from None
        return _full_repo_info(response.json())

    async def _open_pull_request(
        self, github: GitHub[Any], installation_id: int, owner: str, repo: str, head: str
    ) -> PullRequestInfo | None:
        with _github_errors(installation_id, not_found=f"repo {owner}/{repo} not found"):
            response = await github.rest.pulls.async_list(
                owner, repo, state="open", head=f"{owner}:{head}", per_page=1
            )
        found = cast(list[Any], response.json())
        return _pull_request_info(found[0]) if found else None

    def _installation(self, installation_id: int) -> GitHub[Any]:
        auth = self._github.auth
        assert isinstance(auth, AppAuthStrategy)
        return self._github.with_auth(auth.as_installation(installation_id))

    def close(self) -> None:
        self._redaction.close()


class _Unprocessable(Exception):
    """GitHub answered 422; `reason` is its message (data from GitHub, never a token)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@contextmanager
def _github_errors(
    installation_id: int, *, not_found: str | None = None, forbidden: str | None = None
) -> Generator[None]:
    """Maps githubkit errors to ours. `from None` drops the original, whose request and response
    hold the Authorization header. A 404 is an unknown installation, unless the installation was
    reached (its token was issued) and `not_found` says what is missing instead. A 422 raises
    `_Unprocessable` when `not_found` is given (a call on a repo). A 403 on the call raises
    `RepoCreationNotAllowedError` with `forbidden` when given."""
    try:
        yield
    except GitHubException as exc:
        # A failed installation token request surfaces wrapped in a `RequestError`.
        failed = exc if isinstance(exc, RequestFailed) else exc.__cause__
        if not isinstance(failed, RequestFailed):
            raise GithubApiError(f"GitHub request failed: {type(exc).__name__}") from None
        status = failed.response.status_code
        on_repo = not_found is not None and exc is failed
        if status == 404 and on_repo:
            raise GithubApiError(f"{not_found}, or the GitHub App cannot reach it") from None
        if status == 404:
            raise InstallationNotFoundError(installation_id) from None
        if status == 422 and on_repo:
            raise _Unprocessable(_message(failed)) from None
        if status == 403 and on_repo and forbidden is not None:
            raise RepoCreationNotAllowedError(f"{forbidden}: {_message(failed)}") from None
        raise GithubApiError(f"GitHub returned {status}") from None


def _message(failed: RequestFailed) -> str:
    """GitHub's explanation of a 422: the first detailed error, else the summary."""
    try:
        data = failed.response.json()
    except ValueError:
        return "unprocessable request"
    if not isinstance(data, dict):
        return "unprocessable request"
    errors = cast(list[Any], cast(dict[str, Any], data).get("errors") or [])
    for error in errors:
        if isinstance(error, dict) and (text := cast(dict[str, Any], error).get("message")):
            return str(text)[:300]
    return str(cast(dict[str, Any], data).get("message") or "unprocessable request")[:300]


def _pull_request_info(data: Any) -> PullRequestInfo:
    """The fields we need from a pull request, read from GitHub's JSON. (githubkit's model needs
    every field of the full schema, which test payloads would have to repeat.)"""
    pull = cast(dict[str, Any], data)
    return PullRequestInfo(
        number=int(pull["number"]),
        url=str(pull["html_url"]),
        head=str(pull["head"]["ref"]),
        base=str(pull["base"]["ref"]),
    )


def _full_repo_info(data: Any) -> RepoInfo:
    """A repo read on its own, from GitHub's JSON (see `_pull_request_info` for why not the
    model)."""
    repo = cast(dict[str, Any], data)
    full_name = str(repo["full_name"])
    owner = cast(dict[str, Any] | None, repo.get("owner"))
    created_at = repo.get("created_at")
    return RepoInfo(
        id=int(repo["id"]),
        full_name=full_name,
        name=str(repo["name"]),
        owner=str(owner["login"]) if owner else full_name.split("/", 1)[0],
        private=bool(repo["private"]),
        default_branch=str(repo.get("default_branch") or "main"),
        html_url=str(repo["html_url"]),
        created_at=datetime.fromisoformat(str(created_at)) if created_at else None,
    )


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
