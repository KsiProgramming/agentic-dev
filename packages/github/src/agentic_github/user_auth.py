"""A person's own GitHub account (8.2): the OAuth flow that connects it, and what is kept.

This is the second GitHub identity of the platform and it is kept apart from the first. The
company's GitHub App (`GithubApp`) reads repos and opens pull requests; a person's grant exists
only so a run they start can use their own Copilot subscription (a Copilot seat belongs to one
person). Nothing here is ever used to read a repo or open a pull request.

`GithubUserAuth` is the contract; `GithubUserOAuth` talks to github.com, `FakeGithubUserAuth`
stands in for it in local dev and tests. The token kinds GitHub issues for a user are `gho_`
(OAuth app, no expiry unless the app opted in) and `ghu_` (GitHub App user token, 8 hours, with a
refresh token that rotates); a grant holds whichever it got, and `expires_at` and
`refresh_token` are set only when it has them.

Error messages carry a fixed reason, never a code, a token or a response body."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any, Protocol, Self, cast
from urllib.parse import urlencode

import httpx2
from pydantic import SecretStr

from agentic_github.errors import GithubApiError, GithubConfigError

OAUTH_URL = "https://github.com/login/oauth"
USER_API_URL = "https://api.github.com/user"
TIMEOUT_S = 10.0


class GithubUserAuthError(RuntimeError):
    """GitHub refused a grant. `reason` is fixed: `exchange` (the code was not accepted) or
    `invalid_grant` (the refresh token is unknown, expired or revoked)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"GitHub refused the grant: {reason}")
        self.reason = reason


class GithubUserUnauthorizedError(RuntimeError):
    """GitHub did not accept the access token (expired, or the person revoked the app)."""


@dataclass(frozen=True)
class GithubUserOAuthConfig:
    """The deployment's OAuth app for personal connections: its client id and secret, the
    callback URL registered for it (`<API>/github-user/callback`) and the scopes asked for."""

    client_id: str
    client_secret: SecretStr
    redirect_uri: str
    scopes: tuple[str, ...] = ()

    @classmethod
    def from_file(
        cls,
        client_id: str,
        client_secret_file: Path,
        redirect_uri: str,
        scopes: Sequence[str] = (),
    ) -> Self:
        try:
            secret = client_secret_file.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise GithubConfigError(
                f"cannot read the GitHub OAuth client secret {client_secret_file}: "
                f"{type(exc).__name__}"
            ) from None
        if not secret:
            raise GithubConfigError(f"{client_secret_file} is empty")
        return cls(client_id, SecretStr(secret), redirect_uri, tuple(scopes))


@dataclass(frozen=True)
class UserGrant:
    """What GitHub issued to a person. `repr` hides the tokens."""

    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()

    def to_secret(self) -> SecretStr:
        """The grant as the one secret the store encrypts."""
        return SecretStr(
            json.dumps(
                {
                    "access_token": self.access_token.get_secret_value(),
                    "refresh_token": self.refresh_token.get_secret_value()
                    if self.refresh_token
                    else None,
                    "expires_at": self.expires_at.astimezone(UTC).isoformat()
                    if self.expires_at
                    else None,
                    "scopes": list(self.scopes),
                }
            )
        )

    @classmethod
    def from_secret(cls, secret: SecretStr) -> Self:
        data = cast(dict[str, Any], json.loads(secret.get_secret_value()))
        refresh = data.get("refresh_token")
        expires = data.get("expires_at")
        return cls(
            access_token=SecretStr(str(data["access_token"])),
            refresh_token=SecretStr(str(refresh)) if refresh else None,
            expires_at=datetime.fromisoformat(str(expires)) if expires else None,
            scopes=tuple(str(s) for s in data.get("scopes") or ()),
        )


@dataclass(frozen=True)
class GithubUser:
    """The GitHub account that consented: its stable id and the login shown."""

    id: int
    login: str


class GithubUserAuth(Protocol):
    """Raises `GithubUserAuthError` when GitHub refuses a code or refresh token,
    `GithubUserUnauthorizedError` when it refuses an access token, and `GithubApiError` when it
    could not be reached."""

    def authorize_url(self, state: str) -> str: ...

    async def exchange(self, code: str) -> UserGrant: ...

    async def refresh(self, refresh_token: SecretStr) -> UserGrant: ...

    async def user(self, token: SecretStr) -> GithubUser: ...

    async def aclose(self) -> None: ...


class GithubUserOAuth:
    """Has `GithubUserAuth`'s interface. `transport` is for tests."""

    def __init__(
        self,
        config: GithubUserOAuthConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_S, transport=transport)

    def authorize_url(self, state: str) -> str:
        query = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "state": state,
        }
        if self._config.scopes:
            query["scope"] = " ".join(self._config.scopes)
        return f"{OAUTH_URL}/authorize?{urlencode(query)}"

    async def exchange(self, code: str) -> UserGrant:
        body = await self._token(
            {"code": code, "redirect_uri": self._config.redirect_uri}, refused="exchange"
        )
        return _grant(body)

    async def refresh(self, refresh_token: SecretStr) -> UserGrant:
        body = await self._token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token.get_secret_value()},
            refused="invalid_grant",
        )
        return _grant(body)

    async def user(self, token: SecretStr) -> GithubUser:
        try:
            response = await self._http.get(
                USER_API_URL,
                headers={
                    "Authorization": f"Bearer {token.get_secret_value()}",
                    "Accept": "application/vnd.github+json",
                },
            )
        except httpx2.HTTPError as exc:
            raise GithubApiError(f"GitHub could not be reached: {type(exc).__name__}") from None
        if response.status_code == 401:
            raise GithubUserUnauthorizedError("GitHub did not accept the access token")
        if response.status_code != 200:
            raise GithubApiError(f"GitHub answered {response.status_code}")
        body = _object(response)
        user_id, login = body.get("id"), body.get("login")
        if not isinstance(user_id, int) or not isinstance(login, str) or not login:
            raise GithubApiError("GitHub answered with an unexpected body")
        return GithubUser(id=user_id, login=login)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _token(self, form: dict[str, str], *, refused: str) -> dict[str, Any]:
        """POST to the token endpoint. GitHub answers `200` with an `error` for a refusal."""
        data = {
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret.get_secret_value(),
            **form,
        }
        try:
            response = await self._http.post(
                f"{OAUTH_URL}/access_token", data=data, headers={"Accept": "application/json"}
            )
        except httpx2.HTTPError as exc:
            raise GithubApiError(f"GitHub could not be reached: {type(exc).__name__}") from None
        if response.status_code >= 500:
            raise GithubApiError(f"GitHub answered {response.status_code}")
        body = _object(response)
        if response.status_code != 200 or "error" in body or "access_token" not in body:
            raise GithubUserAuthError(refused)
        return body


def _object(response: httpx2.Response) -> dict[str, Any]:
    try:
        body: object = response.json()
    except ValueError:
        raise GithubApiError("GitHub answered with an unexpected body") from None
    if not isinstance(body, dict):
        raise GithubApiError("GitHub answered with an unexpected body")
    return cast(dict[str, Any], body)


def _grant(body: dict[str, Any]) -> UserGrant:
    expires_in = body.get("expires_in")
    refresh = body.get("refresh_token")
    scope = body.get("scope")
    return UserGrant(
        access_token=SecretStr(str(body["access_token"])),
        refresh_token=SecretStr(refresh) if isinstance(refresh, str) and refresh else None,
        expires_at=datetime.now(UTC) + timedelta(seconds=int(expires_in))
        if isinstance(expires_in, int | str) and str(expires_in).isdigit()
        else None,
        scopes=tuple(s for s in str(scope).replace(",", " ").split() if s)
        if isinstance(scope, str)
        else (),
    )


# --- The fake ---

FAKE_USERS: dict[str, GithubUser] = {
    "ada": GithubUser(id=1001, login="ada"),
    "grace": GithubUser(id=1002, login="grace"),
}
FAKE_CODE_PREFIX = "fake-user-code-"
_ACCESS = "gho_fake"
_REFRESH = "ghr_fake"


@dataclass
class FakeGithubUserAuth:
    """Has `GithubUserAuth`'s interface, with no network. Its consent screen is skipped: the
    authorize URL sends the browser straight back to the API's callback as the person `login`
    (`ada` by default). Tests switch its behaviour on the fields below."""

    api_base_url: str
    login: str = "ada"
    expires_in_s: int | None = None
    """Set it and the grants carry a refresh token and expire (a GitHub App's user token)."""
    refuse_refresh: bool = False
    unauthorized: bool = False
    unavailable: bool = False
    refreshes: int = 0
    issued: list[UserGrant] = field(default_factory=list[UserGrant])
    _numbers: "count[int]" = field(default_factory=lambda: count(1))

    def authorize_url(self, state: str) -> str:
        code = f"{FAKE_CODE_PREFIX}{self.login}"
        return (
            f"{self.api_base_url}/github-user/callback?{urlencode({'code': code, 'state': state})}"
        )

    async def exchange(self, code: str) -> UserGrant:
        self._reachable()
        login = code.removeprefix(FAKE_CODE_PREFIX)
        if not code.startswith(FAKE_CODE_PREFIX) or login not in FAKE_USERS:
            raise GithubUserAuthError("exchange")
        return self._issue(login)

    async def refresh(self, refresh_token: SecretStr) -> UserGrant:
        self._reachable()
        self.refreshes += 1
        value = refresh_token.get_secret_value()
        if self.refuse_refresh or not value.startswith(_REFRESH):
            raise GithubUserAuthError("invalid_grant")
        return self._issue(value.split("-")[1])

    async def user(self, token: SecretStr) -> GithubUser:
        self._reachable()
        value = token.get_secret_value()
        if self.unauthorized or not value.startswith(_ACCESS):
            raise GithubUserUnauthorizedError("GitHub did not accept the access token")
        return FAKE_USERS[value.split("-")[1]]

    async def aclose(self) -> None:
        return None

    def _issue(self, login: str) -> UserGrant:
        number = next(self._numbers)
        expiring = self.expires_in_s is not None
        grant = UserGrant(
            access_token=SecretStr(f"{_ACCESS}-{login}-{number:04d}"),
            refresh_token=SecretStr(f"{_REFRESH}-{login}-{number:04d}") if expiring else None,
            expires_at=datetime.now(UTC) + timedelta(seconds=self.expires_in_s)
            if self.expires_in_s is not None
            else None,
        )
        self.issued.append(grant)
        return grant

    def _reachable(self) -> None:
        if self.unavailable:
            raise GithubApiError("GitHub could not be reached: ConnectError")
