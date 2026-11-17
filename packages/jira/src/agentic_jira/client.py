"""The deployment's Atlassian OAuth 2.0 (3LO) app, talking to Atlassian.

All JSON: the authorization-code exchange and the refresh (`auth.atlassian.com`), the
consenting account and the sites the grant reaches (`api.atlassian.com`), and, on a site's REST
API v3 (`api.atlassian.com/ex/jira/<cloud id>`), its projects (7.1), its issues, their
comments and transitions (7.2), and its fields (7.4). No token, code or response body is ever
put in a log line or an exception message: errors carry a status code or a kind. Rich text is
converted to and from Markdown here (`agentic_jira.adf`), so nothing above the client sees ADF."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote, urlencode

import httpx2
from pydantic import SecretStr

from agentic_jira.adf import from_markdown, to_markdown
from agentic_jira.config import AtlassianAppConfig
from agentic_jira.errors import (
    JiraApiError,
    JiraAuthError,
    JiraBadRequestError,
    JiraNotFoundError,
    JiraRateLimitedError,
    JiraUnauthorizedError,
    JiraWebhookError,
)
from agentic_jira.models import (
    SCOPES,
    WEBHOOK_EVENTS,
    WEBHOOK_FIELDS,
    Account,
    DeliveryClaims,
    Grant,
    Issue,
    IssueComment,
    IssueSummary,
    JiraField,
    Project,
    ProjectPage,
    SearchPage,
    Site,
    Transition,
    Webhook,
)
from agentic_jira.webhooks import verify_delivery

AUTH_URL = "https://auth.atlassian.com"
API_URL = "https://api.atlassian.com"
TIMEOUT_S = 10.0
PAGE_SIZE = 50
# Jira's project search takes at most this many `id` parameters.
MAX_IDS = 50
MAX_RETRY_AFTER_S = 10.0
"""A `429` asking for a longer wait than this is not retried (`JiraRateLimitedError`)."""
ISSUE_COMMENTS = 20
"""How many of an issue's latest comments `get_issue` reads."""
ISSUE_FIELDS = (
    "summary,status,issuetype,priority,labels,components,assignee,reporter,created,updated,"
    "description,project"
)
SEARCH_FIELDS = "summary,status,issuetype,assignee,updated,project"
WEBHOOK_PAGE = 100

type _Json = dict[str, Any]


class AtlassianApp:
    """Has `JiraPlatform`'s interface. `transport` and `sleep` are for tests."""

    def __init__(
        self,
        config: AtlassianAppConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._http = httpx2.AsyncClient(timeout=TIMEOUT_S, transport=transport)
        self._sleep = sleep

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

    async def get_issue(
        self, token: SecretStr, cloud_id: str, key: str, *, extra_fields: Sequence[str] = ()
    ) -> Issue:
        """The issue's standard fields, the raw values of `extra_fields` (field ids, 7.4) and
        its latest `ISSUE_COMMENTS` comments, oldest first. `JiraNotFoundError` when it does not
        exist or the account cannot see it."""
        url = _issue_url(cloud_id, key)
        fields = ",".join((ISSUE_FIELDS, *sorted(set(extra_fields))))
        body = _object(await self._get(token, url, [("fields", fields)]))
        page = _object(
            await self._get(
                token,
                f"{url}/comment",
                [("orderBy", "-created"), ("maxResults", str(ISSUE_COMMENTS))],
            )
        )
        return _issue(body, page, extra_fields)

    async def list_fields(self, token: SecretStr, cloud_id: str) -> list[JiraField]:
        """The site's fields (`/rest/api/3/field`), system and custom, team-managed projects'
        own fields among them, by name."""
        body = await self._get(token, f"{_site_api(cloud_id)}/field")
        if not isinstance(body, list):
            raise JiraApiError("Atlassian answered with an unexpected body")
        found = [_field(_object(raw)) for raw in cast(list[Any], body)]
        return sorted((f for f in found if f.id), key=lambda f: (f.name.lower(), f.id))

    async def search(
        self,
        token: SecretStr,
        cloud_id: str,
        jql: str,
        *,
        limit: int,
        page_token: str | None = None,
    ) -> SearchPage:
        """Issues matching `jql`, as given (the caller scopes it). `JiraBadRequestError` for a
        query Jira cannot run."""
        params = [("jql", jql), ("maxResults", str(limit)), ("fields", SEARCH_FIELDS)]
        if page_token:
            params.append(("nextPageToken", page_token))
        body = _object(await self._get(token, f"{_site_api(cloud_id)}/search/jql", params))
        raw = body.get("issues")
        if not isinstance(raw, list):
            raise JiraApiError("Atlassian answered with an unexpected body")
        issues = tuple(_summary(_object(entry)) for entry in cast(list[Any], raw))
        next_token = body.get("nextPageToken")
        last = body.get("isLast") is True or not isinstance(next_token, str) or not next_token
        return SearchPage(issues=issues, next_page_token=None if last else str(next_token))

    async def transitions(self, token: SecretStr, cloud_id: str, key: str) -> list[Transition]:
        """The transitions the issue's workflow offers from its current status."""
        body = _object(await self._get(token, f"{_issue_url(cloud_id, key)}/transitions"))
        raw = body.get("transitions")
        if not isinstance(raw, list):
            raise JiraApiError("Atlassian answered with an unexpected body")
        found: list[Transition] = []
        for entry in cast(list[Any], raw):
            t = _object(entry)
            found.append(
                Transition(
                    id=str(t.get("id", "")),
                    name=str(t.get("name", "")),
                    to_status=_name(t.get("to")) or "",
                )
            )
        return found

    async def add_comment(self, token: SecretStr, cloud_id: str, key: str, body: str) -> str:
        """Posts Markdown `body` as a comment (converted to ADF); its id."""
        answer = _object(
            await self._send(
                "POST",
                token,
                f"{_issue_url(cloud_id, key)}/comment",
                json={"body": from_markdown(body)},
            )
        )
        return str(answer.get("id", ""))

    async def transition(
        self, token: SecretStr, cloud_id: str, key: str, transition_id: str
    ) -> None:
        """Moves the issue through the transition `transition_id`."""
        await self._send(
            "POST",
            token,
            f"{_issue_url(cloud_id, key)}/transitions",
            json={"transition": {"id": transition_id}},
        )

    def verify_delivery(self, authorization: str | None) -> DeliveryClaims:
        """A webhook delivery's claims, checked against this app's client id and secret (7.3)."""
        return verify_delivery(
            authorization,
            client_id=self._config.client_id,
            client_secret=self._config.client_secret.get_secret_value(),
        )

    async def register_webhook(
        self, token: SecretStr, cloud_id: str, url: str, project_keys: Sequence[str]
    ) -> int:
        """Registers one webhook for `WEBHOOK_EVENTS` on the projects, filtered to
        `WEBHOOK_FIELDS`; its id. `JiraWebhookError` when Jira refuses it."""
        body = _object(
            await self._send(
                "POST",
                token,
                f"{_site_api(cloud_id)}/webhook",
                json={
                    "url": url,
                    "webhooks": [
                        {
                            "events": list(WEBHOOK_EVENTS),
                            "jqlFilter": project_filter(project_keys),
                            "fieldIdsFilter": list(WEBHOOK_FIELDS),
                        }
                    ],
                },
            )
        )
        results = body.get("webhookRegistrationResult")
        if not isinstance(results, list) or not results:
            raise JiraApiError("Atlassian answered with an unexpected body")
        result = _object(cast(list[Any], results)[0])
        created = result.get("createdWebhookId")
        if isinstance(created, int) and not isinstance(created, bool):
            return created
        raise JiraWebhookError(_webhook_refusal(result.get("errors")))

    async def list_webhooks(self, token: SecretStr, cloud_id: str) -> list[Webhook]:
        """The webhooks this app registered on the site with this account."""
        found: list[Webhook] = []
        start = 0
        while True:
            params = [("startAt", str(start)), ("maxResults", str(WEBHOOK_PAGE))]
            body = _object(await self._get(token, f"{_site_api(cloud_id)}/webhook", params))
            values = body.get("values")
            if not isinstance(values, list):
                raise JiraApiError("Atlassian answered with an unexpected body")
            for raw in cast(list[Any], values):
                entry = _object(raw)
                webhook_id = entry.get("id")
                if isinstance(webhook_id, int) and not isinstance(webhook_id, bool):
                    found.append(
                        Webhook(
                            id=webhook_id,
                            url=str(entry.get("url", "")),
                            jql_filter=str(entry.get("jqlFilter", "")),
                            expires_at=_when(entry.get("expirationDate")),
                        )
                    )
            if body.get("isLast") is not False or not values:
                return found
            start += len(cast(list[Any], values))

    async def refresh_webhooks(
        self, token: SecretStr, cloud_id: str, ids: Sequence[int]
    ) -> datetime | None:
        """Extends the webhooks' life by 30 days; their new expiry. Jira answers the same for an
        id it does not know, so this cannot tell that one is gone (`list_webhooks` can)."""
        body = _object(
            await self._send(
                "PUT",
                token,
                f"{_site_api(cloud_id)}/webhook/refresh",
                json={"webhookIds": list(ids)},
            )
        )
        return _when(body.get("expirationDate"))

    async def delete_webhooks(self, token: SecretStr, cloud_id: str, ids: Sequence[int]) -> None:
        await self._send(
            "DELETE", token, f"{_site_api(cloud_id)}/webhook", json={"webhookIds": list(ids)}
        )

    async def project_statuses(self, token: SecretStr, cloud_id: str, key: str) -> list[str]:
        """The names of the statuses the project's issue types use, each once, in Jira's
        order."""
        body = await self._get(
            token, f"{_site_api(cloud_id)}/project/{quote(key, safe='')}/statuses"
        )
        if not isinstance(body, list):
            raise JiraApiError("Atlassian answered with an unexpected body")
        names: dict[str, None] = {}
        for raw in cast(list[Any], body):
            statuses = _object(raw).get("statuses")
            if isinstance(statuses, list):
                for status in cast(list[Any], statuses):
                    name = _name(status)
                    if name:
                        names.setdefault(name, None)
        return list(names)

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
        return await self._send("GET", token, url, params=params)

    async def _send(
        self,
        method: str,
        token: SecretStr,
        url: str,
        *,
        params: Sequence[tuple[str, str]] = (),
        json: object = None,
    ) -> object:
        """One call with the bearer token. A `429` is retried once after its `Retry-After`
        (at most `MAX_RETRY_AFTER_S`); a `204`, or a `202` with no body, is `None`."""
        headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept": "application/json",
        }
        retried = False
        while True:
            try:
                response = await self._http.request(
                    method, url, headers=headers, params=list(params), json=json
                )
            except httpx2.HTTPError as exc:
                raise JiraApiError(
                    f"Atlassian could not be reached: {type(exc).__name__}"
                ) from None
            if response.status_code == 401:
                raise JiraUnauthorizedError("Atlassian did not accept the access token")
            if response.status_code == 429:
                wait = _retry_after(response)
                if retried or wait is None:
                    raise JiraRateLimitedError("Atlassian answered 429")
                retried = True
                await self._sleep(wait)
                continue
            if response.status_code == 204 or (
                response.status_code == 202 and not response.content
            ):
                return None  # `DELETE /webhook` answers 202 with no body
            return _json(response)


def _json(response: httpx2.Response) -> object:
    status = response.status_code
    if status == 404:
        raise JiraNotFoundError("Atlassian answered 404")
    if status == 400:
        raise JiraBadRequestError("Atlassian answered 400")
    if status >= 400:
        raise JiraApiError(f"Atlassian answered {status}")
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


def _retry_after(response: httpx2.Response) -> float | None:
    """The wait a `429` asks for, if we take it: seconds only (not an HTTP date); 1 s when it
    names none; `None` past `MAX_RETRY_AFTER_S`."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return 1.0
    try:
        wait = float(raw)
    except ValueError:
        return None
    return max(wait, 0.0) if wait <= MAX_RETRY_AFTER_S else None


def project_filter(project_keys: Sequence[str]) -> str:
    """A webhook's `jqlFilter`: the projects, sorted and quoted (`project in ("API", "OPS")`)."""
    keys = ", ".join(f'"{key}"' for key in sorted(set(project_keys)))
    return f"project in ({keys})"


def _webhook_refusal(errors: object) -> str:
    """The fixed kind for Jira's reasons for refusing a webhook; its words are not kept."""
    text = " ".join(str(e) for e in cast(list[Any], errors)) if isinstance(errors, list) else ""
    lowered = text.lower()
    if "single url" in lowered:
        return "url_conflict"
    if "limit" in lowered or "maximum" in lowered or "exceed" in lowered:
        return "limit"
    return "refused"


def _when(value: object) -> datetime | None:
    """A Jira timestamp (`2026-12-17T11:36:25.653+0100`) or epoch milliseconds, in UTC."""
    if isinstance(value, int) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).astimezone(UTC)
        except ValueError:
            return None
    return None


def _site_api(cloud_id: str) -> str:
    return f"{API_URL}/ex/jira/{quote(cloud_id, safe='')}/rest/api/3"


def _issue_url(cloud_id: str, key: str) -> str:
    return f"{_site_api(cloud_id)}/issue/{quote(key, safe='')}"


def _name(value: object, field: str = "name") -> str | None:
    """`value[field]` when `value` is an object with a non-empty string there."""
    if isinstance(value, dict):
        found = cast(_Json, value).get(field)
        if isinstance(found, str) and found:
            return found
    return None


def _person(value: object) -> str | None:
    return _name(value, "displayName")


def _strings(value: object, field: str | None = None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in cast(list[Any], value):
        text = _name(item, field) if field else (item if isinstance(item, str) else None)
        if text:
            out.append(text)
    return tuple(out)


def _fields(body: _Json) -> _Json:
    fields = body.get("fields")
    return cast(_Json, fields) if isinstance(fields, dict) else {}


def _project_key(key: str, fields: _Json) -> str:
    return _name(fields.get("project"), "key") or key.rsplit("-", 1)[0]


def _field(entry: _Json) -> JiraField:
    schema = entry.get("schema")
    schema = cast(_Json, schema) if isinstance(schema, dict) else {}
    custom = schema.get("custom")
    scope = entry.get("scope")
    project = _name(cast(_Json, scope).get("project"), "id") if isinstance(scope, dict) else None
    return JiraField(
        id=str(entry.get("id", "")),
        name=str(entry.get("name") or entry.get("id") or ""),
        type=str(schema.get("type") or ""),
        kind=custom.rsplit(":", 1)[-1] if isinstance(custom, str) else "",
        custom=entry.get("custom") is True,
        project_id=project,
    )


def _issue(body: _Json, comments: _Json, extra_fields: Sequence[str] = ()) -> Issue:
    key = str(body.get("key", ""))
    fields = _fields(body)
    raw = comments.get("comments")
    found: list[IssueComment] = []
    if isinstance(raw, list):
        for entry in cast(list[Any], raw):
            c = _object(entry)
            found.append(
                IssueComment(
                    id=str(c.get("id", "")),
                    author=_person(c.get("author")) or "Unknown",
                    created=str(c.get("created", "")),
                    body=to_markdown(c.get("body")),
                )
            )
    found.reverse()  # read newest first, shown oldest first
    total = comments.get("total")
    return Issue(
        id=str(body.get("id", "")),
        key=key,
        project_key=_project_key(key, fields),
        summary=str(fields.get("summary") or ""),
        status=_name(fields.get("status")) or "",
        type=_name(fields.get("issuetype")) or "",
        priority=_name(fields.get("priority")),
        labels=_strings(fields.get("labels")),
        components=_strings(fields.get("components"), "name"),
        assignee=_person(fields.get("assignee")),
        reporter=_person(fields.get("reporter")),
        created=str(fields.get("created") or ""),
        updated=str(fields.get("updated") or ""),
        description=to_markdown(fields.get("description")),
        comments=tuple(found),
        comment_count=total if isinstance(total, int) else len(found),
        extra={f: fields[f] for f in extra_fields if fields.get(f) is not None},
    )


def _summary(body: _Json) -> IssueSummary:
    key = str(body.get("key", ""))
    fields = _fields(body)
    return IssueSummary(
        key=key,
        project_key=_project_key(key, fields),
        summary=str(fields.get("summary") or ""),
        status=_name(fields.get("status")) or "",
        type=_name(fields.get("issuetype")) or "",
        assignee=_person(fields.get("assignee")),
        updated=str(fields.get("updated") or ""),
    )
