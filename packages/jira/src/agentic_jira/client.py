"""The deployment's Atlassian OAuth 2.0 (3LO) app, talking to Atlassian.

Five calls, all JSON: the authorization-code exchange and the refresh (`auth.atlassian.com`),
the consenting account and the sites the grant reaches (`api.atlassian.com`), and a site's
projects (`api.atlassian.com/ex/jira/<cloud id>`). No token, code or response body is ever put
in a log line or an exception message: errors carry a status code or a kind."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx2
from pydantic import SecretStr

from agentic_jira.config import AtlassianAppConfig
from agentic_jira.errors import JiraApiError, JiraAuthError, JiraUnauthorizedError
from agentic_jira.models import SCOPES, Account, Grant, Project, ProjectPage, Site

AUTH_URL = "https://auth.atlassian.com"
API_URL = "https://api.atlassian.com"
TIMEOUT_S = 10.0
PAGE_SIZE = 50
# Jira's project search takes at most this many `id` parameters.
MAX_IDS = 50

type _Json = dict[str, Any]


class AtlassianApp:
    """Has `JiraPlatform`'s interface. `transport` is for tests."""

    def __init__(
        self, config: AtlassianAppConfig, *, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self._config = config
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_S, transport=transport)

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "audience": "api.atlassian.com",
                "client_id": self._config.client_id,
                "scope": " ".join(SCOPES),
                "redirect_uri": self._config.redirect_uri,
                "state": state,
                "response_type": "code",
                "prompt": "consent",
            }
        )
        return f"{AUTH_URL}/authorize?{query}"

    async def exchange(self, code: str) -> Grant:
        body = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._config.redirect_uri,
            },
            refused="exchange",
        )
        refresh_token = body.get("refresh_token")
        if not isinstance(refresh_token, str):
            # No `offline_access`: the grant could not outlive its first hour.
            raise JiraAuthError("exchange")
        return _grant(body, refresh_token)

    async def refresh(self, refresh_token: SecretStr) -> Grant:
        current = refresh_token.get_secret_value()
        body = await self._token(
            {"grant_type": "refresh_token", "refresh_token": current}, refused="invalid_grant"
        )
        rotated = body.get("refresh_token")
        return _grant(body, rotated if isinstance(rotated, str) else current)

    async def account(self, token: SecretStr) -> Account:
        body = _object(await self._get(token, f"{API_URL}/me"))
        account_id = str(body.get("account_id", ""))
        name = body.get("name") or body.get("nickname") or body.get("email") or account_id
        return Account(account_id=account_id, name=str(name))

    async def sites(self, token: SecretStr) -> list[Site]:
        """The Jira sites the grant reaches. Atlassian lists a site once per product the grant
        covers; one without a Jira scope is not a Jira site."""
        body = await self._get(token, f"{API_URL}/oauth/token/accessible-resources")
        if not isinstance(body, list):
            raise JiraApiError("Atlassian answered with an unexpected body")
        found: dict[str, Site] = {}
        for raw in cast(list[Any], body):
            entry = _object(raw)
            scopes = entry.get("scopes")
            if isinstance(scopes, list) and not any(
                "jira" in str(scope) for scope in cast(list[Any], scopes)
            ):
                continue
            cloud_id = str(entry.get("id", ""))
            if cloud_id:
                found.setdefault(
                    cloud_id,
                    Site(
                        cloud_id=cloud_id,
                        url=str(entry.get("url", "")),
                        name=str(entry.get("name") or entry.get("url") or cloud_id),
                    ),
                )
        return sorted(found.values(), key=lambda site: site.name.lower())

    async def search_projects(
        self, token: SecretStr, cloud_id: str, *, query: str = "", start_at: int = 0
    ) -> ProjectPage:
        params: list[tuple[str, str]] = [
            ("startAt", str(start_at)),
            ("maxResults", str(PAGE_SIZE)),
            ("orderBy", "name"),
        ]
        if query:
            params.append(("query", query))
        body = _object(await self._get(token, _project_search(cloud_id), params))
        projects = _projects(body)
        last = body.get("isLast") is not False or not projects
        return ProjectPage(
            projects=projects, next_start_at=None if last else start_at + len(projects)
        )

    async def get_projects(
        self, token: SecretStr, cloud_id: str, ids: Sequence[str]
    ) -> list[Project]:
        """The projects among `ids` the grant's account can see on the site."""
        found: list[Project] = []
        for start in range(0, len(ids), MAX_IDS):
            chunk = ids[start : start + MAX_IDS]
            params = [("maxResults", str(MAX_IDS)), *(("id", project_id) for project_id in chunk)]
            found.extend(
                _projects(_object(await self._get(token, _project_search(cloud_id), params)))
            )
        return found

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _token(self, grant: Mapping[str, str], *, refused: str) -> _Json:
        payload = {
            **grant,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret.get_secret_value(),
        }
        try:
            response = await self._http.post(f"{AUTH_URL}/oauth/token", json=payload)
        except httpx2.HTTPError as exc:
            raise JiraApiError(f"Atlassian could not be reached: {type(exc).__name__}") from None
        if response.status_code in (400, 401, 403):
            raise JiraAuthError(refused)
        body = _json(response)
        if not isinstance(body, dict) or not isinstance(cast(_Json, body).get("access_token"), str):
            raise JiraApiError("Atlassian answered with an unexpected body")
        return cast(_Json, body)

    async def _get(
        self, token: SecretStr, url: str, params: Sequence[tuple[str, str]] = ()
    ) -> object:
        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept": "application/json",
        }
        try:
            response = await self._http.get(url, headers=headers, params=list(params))
        except httpx2.HTTPError as exc:
            raise JiraApiError(f"Atlassian could not be reached: {type(exc).__name__}") from None
        if response.status_code == 401:
            raise JiraUnauthorizedError("Atlassian did not accept the access token")
        return _json(response)


def _json(response: httpx2.Response) -> object:
    if response.status_code >= 400:
        raise JiraApiError(f"Atlassian answered {response.status_code}")
    try:
        return cast(object, response.json())
    except ValueError:
        raise JiraApiError("Atlassian answered with an unexpected body") from None


def _object(value: object) -> _Json:
    if not isinstance(value, dict):
        raise JiraApiError("Atlassian answered with an unexpected body")
    return cast(_Json, value)


def _grant(body: _Json, refresh_token: str) -> Grant:
    expires_in = body.get("expires_in")
    seconds = expires_in if isinstance(expires_in, int) else 3600
    return Grant(
        access_token=SecretStr(str(body["access_token"])),
        refresh_token=SecretStr(refresh_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        scopes=tuple(str(body.get("scope") or "").split()),
    )


def _project_search(cloud_id: str) -> str:
    return f"{API_URL}/ex/jira/{cloud_id}/rest/api/3/project/search"


def _projects(body: _Json) -> tuple[Project, ...]:
    values = body.get("values")
    if not isinstance(values, list):
        raise JiraApiError("Atlassian answered with an unexpected body")
    projects: list[Project] = []
    for raw in cast(list[Any], values):
        entry = _object(raw)
        projects.append(
            Project(
                id=str(entry.get("id", "")),
                key=str(entry.get("key", "")),
                name=str(entry.get("name", "")),
            )
        )
    return tuple(projects)
