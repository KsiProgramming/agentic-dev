"""Linking a workspace to the platform's GitHub App, and listing the repos it can reach.

The install flow: the web app asks for an install URL, which carries a random single-use
`state` kept in Redis for 10 minutes. GitHub sends the browser back to `/github/setup` (the App's
Setup URL) with that state and the installation id. We check the installation belongs to our App
before storing it, then send the browser back to the web app's settings page."""

import secrets
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.github.models import GithubErrorDetail, InstallUrlOut, RepoOut
from agentic_api.settings import Settings
from agentic_github import GithubApiError, GithubApp, InstallationNotFoundError
from agentic_store import (
    GITHUB,
    WorkspaceNotFoundError,
    delete_connection,
    get_github_installation,
    get_workspace,
    put_github_connection,
)

router = APIRouter(tags=["github"])

STATE_TTL_S = 600
_STATE_KEY = "github:install-state:{state}"

_NOT_CONFIGURED: dict[int | str, dict[str, str]] = {
    503: {"description": "The GitHub App is not configured on the API"}
}
_NOT_FOUND: dict[int | str, dict[str, str]] = {404: {"description": "No workspace with this id"}}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def _github(request: Request) -> GithubApp:
    github: GithubApp | None = request.app.state.github
    if github is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the GitHub App is not configured: set GITHUB_APP_ID, GITHUB_APP_SLUG and "
            "GITHUB_APP_PRIVATE_KEY_FILE on the API",
        )
    return github


def _not_found(workspace_id: UUID) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, GithubErrorDetail(code=code, message=message).model_dump()
    )


@router.post(
    "/workspaces/{workspace_id}/connections/github/install",
    operation_id="startGithubInstall",
    responses={**_NOT_FOUND, **_NOT_CONFIGURED},
)
async def start_install(
    workspace_id: UUID, request: Request, github: Annotated[GithubApp, Depends(_github)]
) -> InstallUrlOut:
    """An install URL for the GitHub App. Installing it links the installation to the workspace."""
    if await get_workspace(_sessions(request), workspace_id) is None:
        raise _not_found(workspace_id)
    state = secrets.token_urlsafe(32)
    await _redis(request).set(
        _STATE_KEY.format(state=state), str(workspace_id), ex=STATE_TTL_S, nx=True
    )
    return InstallUrlOut(install_url=github.install_url(state))


@router.get(
    "/github/setup",
    operation_id="completeGithubInstall",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
)
async def complete_install(
    request: Request,
    installation_id: int | None = None,
    setup_action: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """GitHub's redirect after an install (the App's Setup URL). Sends the browser back to the
    web app's settings page with `github=connected`, or `github=error` and a `reason`."""
    settings: Settings = request.app.state.settings
    github: GithubApp | None = request.app.state.github

    def back(**params: str) -> RedirectResponse:
        url = f"{settings.web_base_url.rstrip('/')}/settings?{urlencode(params)}"
        return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)

    # The state is consumed first, so it is single use whatever happens next.
    stored: Any = (
        await _redis(request).getdel(_STATE_KEY.format(state=state))  # pyright: ignore[reportUnknownMemberType]
        if state
        else None
    )
    workspace_id = None if stored is None else UUID(bytes(stored).decode())
    if github is None:
        return back(github="error", reason="not_configured")
    if setup_action == "request":
        # An organisation member asked an owner to install the App; nothing to link yet.
        return back(github="error", reason="pending")
    if workspace_id is None:
        return back(github="error", reason="state")
    if installation_id is None:
        return back(github="error", reason="installation")
    try:
        installation = await github.get_installation(installation_id)
        await put_github_connection(
            _sessions(request),
            workspace_id,
            installation.id,
            installation.account_login,
        )
    except InstallationNotFoundError:
        return back(github="error", reason="installation")
    except GithubApiError:
        return back(github="error", reason="github")
    except WorkspaceNotFoundError:
        return back(github="error", reason="state")
    return back(github="connected")


@router.get(
    "/workspaces/{workspace_id}/repos",
    operation_id="listRepos",
    responses={
        **_NOT_FOUND,
        409: {
            "description": "`no_connection`: the workspace has no GitHub connection. "
            "`installation_gone`: the App was uninstalled or lost access; install it again.",
            "model": GithubErrorDetail,
        },
        502: {"description": "GitHub answered with an error or could not be reached"},
        **_NOT_CONFIGURED,
    },
)
async def repos(
    workspace_id: UUID, request: Request, github: Annotated[GithubApp, Depends(_github)]
) -> list[RepoOut]:
    """The repos the workspace's GitHub App installation can reach, by full name."""
    try:
        installation_id = await get_github_installation(_sessions(request), workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    if installation_id is None:
        raise _conflict("no_connection", "the workspace has no GitHub connection")
    try:
        found = await github.list_repos(installation_id)
    except InstallationNotFoundError:
        raise _conflict(
            "installation_gone",
            "the GitHub App installation no longer exists or lost access; install it again",
        ) from None
    except GithubApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from None
    return [RepoOut.of(r) for r in sorted(found, key=lambda r: r.full_name.lower())]


@router.delete(
    "/workspaces/{workspace_id}/connections/github",
    operation_id="deleteGithubConnection",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "No such workspace, or it has no GitHub connection"}},
)
async def delete_github(workspace_id: UUID, request: Request) -> None:
    """Unlink the workspace from its installation. The App stays installed on GitHub."""
    try:
        deleted = await delete_connection(_sessions(request), workspace_id, GITHUB)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the workspace has no GitHub connection")
