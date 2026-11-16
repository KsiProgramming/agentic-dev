"""Connecting a workspace to Jira (7.1): Atlassian's OAuth 2.0 (3LO) consent, the sites the
grant reaches and the projects the workspace may use on each.

The flow: the web app asks for an authorize URL, which carries a random single-use `state` kept
in Redis for 10 minutes (as the GitHub install does). Atlassian sends the browser back to
`/jira/callback` with that state and a code. We exchange the code, read the account and its
sites, store the grant encrypted, then send the browser back to the web app's settings page.

Atlassian's consent is per site, so project scoping is ours: the workspace picks projects per
site and `jira_project_allowed` (store) is the check the Jira tools make from 7.2. Nothing here
writes to Jira. No token is ever returned, logged or put in a redirect."""

import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.jira.models import (
    AuthorizeUrlOut,
    CloudId,
    JiraConnectionOut,
    JiraErrorDetail,
    JiraProjectOut,
    JiraProjectPage,
    JiraSiteOut,
    PatchJiraSite,
    PutJiraProjects,
    StartAuthorize,
)
from agentic_api.settings import Settings
from agentic_jira import (
    JiraApiError,
    JiraAuthError,
    JiraPlatform,
    JiraUnauthorizedError,
    Project,
    ProjectPage,
    call,
    missing_scopes,
)
from agentic_secrets import KeyProvider, SecretDecryptError, registered
from agentic_store import (
    JIRA,
    JiraNeedsAttentionError,
    JiraNotConnectedError,
    JiraProjectRef,
    JiraSiteRef,
    WorkspaceNotFoundError,
    delete_connection,
    get_jira_connection,
    get_workspace,
    put_jira_connection,
    set_jira_site_enabled,
    set_jira_site_projects,
)

router = APIRouter(tags=["jira"])


class _PendingAuthorize(BaseModel):
    """What a consent's `state` stands for, kept in Redis until Atlassian sends the browser
    back."""

    workspace_id: UUID
    return_to: str | None = None


STATE_TTL_S = 600
_STATE_KEY = "jira:authorize-state:{state}"
SCOPES_REASON = "scopes"

_NOT_CONFIGURED: dict[int | str, dict[str, Any]] = {
    503: {"description": "No Atlassian OAuth app, or no master key, is configured on the API"}
}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No workspace with this id"}}
_SITE_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such workspace, or its Jira connection has no such site"},
    409: {
        "description": "`no_connection`: the workspace has no Jira connection. "
        "`needs_attention`: Atlassian no longer accepts it; connect again.",
        "model": JiraErrorDetail,
    },
    502: {"description": "Atlassian answered with an error or could not be reached"},
    **_NOT_CONFIGURED,
}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def _jira(request: Request) -> JiraPlatform:
    jira: JiraPlatform | None = request.app.state.jira
    if jira is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Jira is not configured: set ATLASSIAN_CLIENT_ID and ATLASSIAN_CLIENT_SECRET_FILE "
            "on the API",
        )
    return jira


def _keys(request: Request) -> KeyProvider:
    keys: KeyProvider | None = request.app.state.keys
    if keys is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "secrets are not configured: set MASTER_KEY_FILE on the API to store keys",
        )
    return keys


def _not_found(workspace_id: UUID) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")


def _no_site(cloud_id: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND, f"the workspace's Jira connection has no site {cloud_id}"
    )


def _refused(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, JiraErrorDetail(code=code, message=message).model_dump())


@router.post(
    "/workspaces/{workspace_id}/connections/jira/authorize",
    operation_id="startJiraAuthorize",
    responses={**_NOT_FOUND, **_NOT_CONFIGURED},
)
async def start_authorize(
    workspace_id: UUID,
    request: Request,
    jira: Annotated[JiraPlatform, Depends(_jira)],
    _: Annotated[KeyProvider, Depends(_keys)],
    body: StartAuthorize | None = None,
) -> AuthorizeUrlOut:
    """Atlassian's consent URL for the workspace. Consenting stores the grant, then sends the
    browser to `return_to` (the Integrations settings page by default)."""
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise _not_found(workspace_id)
    state = secrets.token_urlsafe(32)
    pending = _PendingAuthorize(
        workspace_id=workspace_id, return_to=body.return_to if body else None
    )
    await _redis(request).set(
        _STATE_KEY.format(state=state), pending.model_dump_json(), ex=STATE_TTL_S, nx=True
    )
    return AuthorizeUrlOut(authorize_url=jira.authorize_url(state))


@router.get(
    "/jira/callback",
    operation_id="completeJiraAuthorize",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
)
async def complete_authorize(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Atlassian's redirect after the consent (the OAuth app's callback URL). Sends the browser
    back to the page that started it (the Integrations settings page by default) with
    `jira=connected`, or `jira=error` and a `reason`: `state` (unknown, used or expired),
    `denied` (the person refused), `exchange` (Atlassian refused the code), `no_sites` (the
    account reaches no Jira site), `scopes` (stored, but a scope is missing), `atlassian`
    (Atlassian could not be reached) or `not_configured`."""
    settings: Settings = request.app.state.settings
    jira: JiraPlatform | None = request.app.state.jira
    keys: KeyProvider | None = request.app.state.keys

    # The state is consumed first, so it is single use whatever happens next.
    stored: Any = (
        await _redis(request).getdel(_STATE_KEY.format(state=state))  # pyright: ignore[reportUnknownMemberType]
        if state
        else None
    )
    pending = None if stored is None else _PendingAuthorize.model_validate_json(bytes(stored))
    return_to = (pending.return_to if pending else None) or "/settings/integrations"

    def back(**params: str) -> RedirectResponse:
        separator = "&" if "?" in return_to else "?"
        url = f"{settings.web_base_url.rstrip('/')}{return_to}{separator}{urlencode(params)}"
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)

    if jira is None or keys is None:
        return back(jira="error", reason="not_configured")
    if pending is None:
        return back(jira="error", reason="state")
    if error is not None:
        return back(jira="error", reason="denied")
    if not code:
        return back(jira="error", reason="exchange")
    missing: tuple[str, ...] = ()
    try:
        grant = await jira.exchange(code)
        with registered(grant.access_token), registered(grant.refresh_token):
            account = await jira.account(grant.access_token)
            sites = await jira.sites(grant.access_token)
            if not sites:
                return back(jira="error", reason="no_sites")
            missing = missing_scopes(grant.scopes)
            await put_jira_connection(
                _sessions(request),
                keys,
                pending.workspace_id,
                grant.to_secret(),
                account=account.name,
                scopes=grant.scopes,
                sites=[JiraSiteRef(s.cloud_id, s.url, s.name) for s in sites],
                needs_attention=SCOPES_REASON if missing else None,
            )
    except JiraAuthError:
        return back(jira="error", reason="exchange")
    except (JiraApiError, JiraUnauthorizedError):
        return back(jira="error", reason="atlassian")
    except WorkspaceNotFoundError:
        return back(jira="error", reason="state")
    if missing:
        return back(jira="error", reason=SCOPES_REASON)
    return back(jira="connected")


@router.get(
    "/workspaces/{workspace_id}/jira", operation_id="getJiraConnection", responses=_NOT_FOUND
)
async def jira_connection(workspace_id: UUID, request: Request) -> JiraConnectionOut:
    """The workspace's Jira connection: its account, the sites it reaches and the projects
    picked on each. Reads only what is stored; it never calls Atlassian."""
    try:
        info = await get_jira_connection(_sessions(request), workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return JiraConnectionOut.of(
        info,
        configured=request.app.state.jira is not None,
        missing=() if info is None else missing_scopes(info.scopes),
    )


@router.patch(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}",
    operation_id="patchJiraSite",
    responses={404: {"description": "No such workspace, or its Jira connection has no such site"}},
)
async def patch_site(
    workspace_id: UUID, cloud_id: CloudId, body: PatchJiraSite, request: Request
) -> JiraSiteOut:
    """Turn a site on or off for the workspace. Its picked projects are kept."""
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise _not_found(workspace_id)
    site = await set_jira_site_enabled(_sessions(request), workspace_id, cloud_id, body.enabled)
    if site is None:
        raise _no_site(cloud_id)
    return JiraSiteOut.of(site)


async def _known_site(request: Request, workspace_id: UUID, cloud_id: str) -> None:
    """Raises unless the workspace's Jira connection reaches the site: a cloud id is only ever
    sent to Atlassian when the connection's own grant listed it."""
    try:
        info = await get_jira_connection(_sessions(request), workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    if info is None:
        raise _refused(
            status.HTTP_409_CONFLICT, "no_connection", "the workspace has no Jira connection"
        )
    if all(site.cloud_id != cloud_id for site in info.sites):
        raise _no_site(cloud_id)


async def _from_jira[T](
    request: Request,
    workspace_id: UUID,
    jira: JiraPlatform,
    keys: KeyProvider,
    fetch: Callable[[SecretStr], Awaitable[T]],
) -> T:
    """`fetch(token)` with the workspace's access token, its failures as HTTP errors."""
    try:
        return await call(_sessions(request), keys, jira, workspace_id, fetch)
    except JiraNotConnectedError:
        raise _refused(
            status.HTTP_409_CONFLICT, "no_connection", "the workspace has no Jira connection"
        ) from None
    except JiraNeedsAttentionError:
        raise _refused(
            status.HTTP_409_CONFLICT,
            "needs_attention",
            "Atlassian no longer accepts the workspace's Jira connection; connect it again",
        ) from None
    except SecretDecryptError:
        raise _refused(
            status.HTTP_409_CONFLICT,
            "needs_attention",
            "the stored Jira connection cannot be read with this master key; connect it again",
        ) from None
    except JiraApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None


@router.get(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}/projects",
    operation_id="searchJiraProjects",
    responses=_SITE_ERRORS,
)
async def search_projects(
    workspace_id: UUID,
    cloud_id: CloudId,
    request: Request,
    jira: Annotated[JiraPlatform, Depends(_jira)],
    keys: Annotated[KeyProvider, Depends(_keys)],
    q: Annotated[str, Query(max_length=100)] = "",
    cursor: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> JiraProjectPage:
    """The site's projects the connected account can see, by name, read live from Jira, to
    pick from. `q` filters by key or name."""
    await _known_site(request, workspace_id, cloud_id)

    async def fetch(token: SecretStr) -> ProjectPage:
        return await jira.search_projects(token, cloud_id, query=q.strip(), start_at=cursor)

    page = await _from_jira(request, workspace_id, jira, keys, fetch)
    return JiraProjectPage(
        projects=[JiraProjectOut.of(p) for p in page.projects], next_cursor=page.next_start_at
    )


@router.put(
    "/workspaces/{workspace_id}/jira/sites/{cloud_id}/projects",
    operation_id="putJiraProjects",
    responses={
        **_SITE_ERRORS,
        422: {
            "description": "`unknown_project`: an id is not a project the connected account "
            "can see on the site; nothing was stored. (Or the body is invalid.)",
            "model": JiraErrorDetail,
        },
    },
)
async def put_projects(
    workspace_id: UUID,
    cloud_id: CloudId,
    body: PutJiraProjects,
    request: Request,
    jira: Annotated[JiraPlatform, Depends(_jira)],
    keys: Annotated[KeyProvider, Depends(_keys)],
) -> JiraSiteOut:
    """Replace the projects the workspace may use on the site. Each id is checked with Jira,
    and its key and name are stored as Jira gives them."""
    await _known_site(request, workspace_id, cloud_id)
    ids = list(dict.fromkeys(body.project_ids))

    async def fetch(token: SecretStr) -> list[Project]:
        return await jira.get_projects(token, cloud_id, ids)

    found = await _from_jira(request, workspace_id, jira, keys, fetch) if ids else []
    by_id = {project.id: project for project in found}
    unknown = [project_id for project_id in ids if project_id not in by_id]
    if unknown:
        raise _refused(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "unknown_project",
            f"not a project the connected account can see on this site: {', '.join(unknown[:10])}",
        )
    site = await set_jira_site_projects(
        _sessions(request),
        workspace_id,
        cloud_id,
        [JiraProjectRef(p.id, p.key.upper(), p.name) for p in (by_id[i] for i in ids)],
    )
    if site is None:
        raise _no_site(cloud_id)
    return JiraSiteOut.of(site)


@router.delete(
    "/workspaces/{workspace_id}/connections/jira",
    operation_id="deleteJiraConnection",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "No such workspace, or it has no Jira connection"}},
)
async def delete_jira(workspace_id: UUID, request: Request) -> None:
    """Remove the workspace's grant, its sites and its picked projects. The app's access stays
    listed in the person's Atlassian account until they remove it there."""
    try:
        deleted = await delete_connection(_sessions(request), workspace_id, JIRA)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the workspace has no Jira connection")
