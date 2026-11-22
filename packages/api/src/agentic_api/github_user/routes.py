"""Connecting a person's own GitHub account (8.2), so a run they start can use their Copilot.

The flow is the one Jira's connection uses: the web app asks for an authorize URL, which carries a
random single-use `state` kept in Redis for 10 minutes; GitHub sends the browser back to
`/github-user/callback` with the state and a code; we exchange the code, read the account, store
the grant encrypted and send the browser back to the web app's settings page.

This is a second GitHub identity, apart from the company's GitHub App: nothing here reads a repo
or opens a pull request, and the stored token is only ever given to a run its person started.
No token is ever returned, logged or put in a redirect."""

import secrets
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.github_user.models import (
    GithubUserAuthorizeOut,
    GithubUserConnectionOut,
    GithubUserConnectionsOut,
    StartGithubUserAuthorize,
)
from agentic_api.settings import Settings
from agentic_github import (
    GithubApiError,
    GithubUserAuth,
    GithubUserAuthError,
    GithubUserUnauthorizedError,
)
from agentic_secrets import KeyProvider, registered
from agentic_store import (
    WorkspaceNotFoundError,
    delete_github_user_connection,
    get_workspace,
    list_github_user_connections,
    put_github_user_connection,
)

router = APIRouter(tags=["github-user"])


class _PendingAuthorize(BaseModel):
    """What a consent's `state` stands for, kept in Redis until GitHub sends the browser back."""

    workspace_id: UUID
    return_to: str | None = None


STATE_TTL_S = 600
_STATE_KEY = "github-user:authorize-state:{state}"

_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No workspace with this id"}}
_NOT_CONFIGURED: dict[int | str, dict[str, Any]] = {
    503: {"description": "No GitHub OAuth app, or no master key, is configured on the API"}
}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def github_user_auth(request: Request) -> GithubUserAuth:
    auth: GithubUserAuth | None = request.app.state.github_user
    if auth is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "personal GitHub connections are not configured: set GITHUB_USER_CLIENT_ID and "
            "GITHUB_USER_CLIENT_SECRET_FILE on the API",
        )
    return auth


def master_keys(request: Request) -> KeyProvider:
    keys: KeyProvider | None = request.app.state.keys
    if keys is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "secrets are not configured: set MASTER_KEY_FILE on the API to store keys",
        )
    return keys


def _workspace_not_found(workspace_id: UUID) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")


@router.post(
    "/workspaces/{workspace_id}/connections/github-user/authorize",
    operation_id="startGithubUserAuthorize",
    responses={**_NOT_FOUND, **_NOT_CONFIGURED},
)
async def start_authorize(
    workspace_id: UUID,
    request: Request,
    auth: Annotated[GithubUserAuth, Depends(github_user_auth)],
    _: Annotated[KeyProvider, Depends(master_keys)],
    body: StartGithubUserAuthorize | None = None,
) -> GithubUserAuthorizeOut:
    """GitHub's consent URL for the person connecting. Consenting stores their grant in the
    workspace, then sends the browser to `return_to` (the Integrations settings page by default)."""
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise _workspace_not_found(workspace_id)
    state = secrets.token_urlsafe(32)
    pending = _PendingAuthorize(
        workspace_id=workspace_id, return_to=body.return_to if body else None
    )
    await _redis(request).set(
        _STATE_KEY.format(state=state), pending.model_dump_json(), ex=STATE_TTL_S, nx=True
    )
    return GithubUserAuthorizeOut(authorize_url=auth.authorize_url(state))


@router.get(
    "/github-user/callback",
    operation_id="completeGithubUserAuthorize",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
)
async def complete_authorize(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """GitHub's redirect after the consent (the OAuth app's callback URL). Sends the browser back
    to the page that started it (the Integrations settings page by default) with
    `github_user=connected`, or `github_user=error` and a `reason`: `state` (unknown, used or
    expired), `denied` (the person refused), `exchange` (GitHub refused the code), `github`
    (GitHub could not be reached) or `not_configured`."""
    settings: Settings = request.app.state.settings
    auth: GithubUserAuth | None = request.app.state.github_user
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

    if auth is None or keys is None:
        return back(github_user="error", reason="not_configured")
    if pending is None:
        return back(github_user="error", reason="state")
    if error is not None:
        return back(github_user="error", reason="denied")
    if not code:
        return back(github_user="error", reason="exchange")
    try:
        grant = await auth.exchange(code)
        with registered(grant.access_token):
            user = await auth.user(grant.access_token)
            await put_github_user_connection(
                _sessions(request),
                keys,
                pending.workspace_id,
                github_user_id=user.id,
                login=user.login,
                scopes=list(grant.scopes),
                secret=grant.to_secret(),
            )
    except GithubUserAuthError:
        return back(github_user="error", reason="exchange")
    except (GithubApiError, GithubUserUnauthorizedError):
        return back(github_user="error", reason="github")
    except WorkspaceNotFoundError:
        return back(github_user="error", reason="state")
    return back(github_user="connected")


@router.get(
    "/workspaces/{workspace_id}/github-user",
    operation_id="listGithubUserConnections",
    responses=_NOT_FOUND,
)
async def list_connections(workspace_id: UUID, request: Request) -> GithubUserConnectionsOut:
    """The workspace's personal GitHub connections, one per person. Reads only what is stored;
    it never calls GitHub."""
    try:
        infos = await list_github_user_connections(_sessions(request), workspace_id)
    except WorkspaceNotFoundError:
        raise _workspace_not_found(workspace_id) from None
    return GithubUserConnectionsOut(
        configured=request.app.state.github_user is not None,
        connections=[GithubUserConnectionOut.of(i) for i in infos],
    )


@router.delete(
    "/workspaces/{workspace_id}/github-user/{connection_id}",
    operation_id="deleteGithubUserConnection",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "No such workspace, or it has no such connection"}},
)
async def delete_connection(workspace_id: UUID, connection_id: UUID, request: Request) -> None:
    """Remove the connection and its token. Runs started with it keep the login they recorded.
    The app's access stays listed in the person's GitHub settings, where they can revoke it."""
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise _workspace_not_found(workspace_id)
    if not await delete_github_user_connection(_sessions(request), workspace_id, connection_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the workspace has no such connection")
