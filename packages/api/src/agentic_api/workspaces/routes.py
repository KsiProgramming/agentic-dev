from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api.workspaces.models import ConnectionOut, PutClaudeConnection, WorkspaceOut
from agentic_secrets import KeyProvider
from agentic_store import (
    WorkspaceNotFoundError,
    delete_connection,
    list_connections,
    list_workspaces,
    put_connection,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_NOT_FOUND: dict[int | str, dict[str, str]] = {404: {"description": "No workspace with this id"}}


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessions


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


@router.get("", operation_id="listWorkspaces")
async def workspaces(request: Request) -> list[WorkspaceOut]:
    return [WorkspaceOut.of(w) for w in await list_workspaces(_sessions(request))]


@router.get("/{workspace_id}/connections", operation_id="listConnections", responses=_NOT_FOUND)
async def connections(workspace_id: UUID, request: Request) -> list[ConnectionOut]:
    """The workspace's connections, without their secrets."""
    try:
        found = await list_connections(_sessions(request), workspace_id)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return [ConnectionOut.of(c) for c in found if c.provider == "claude"]


@router.put(
    "/{workspace_id}/connections/claude",
    operation_id="putClaudeConnection",
    responses={**_NOT_FOUND, 503: {"description": "No master key is configured"}},
)
async def put_claude(
    workspace_id: UUID,
    body: PutClaudeConnection,
    request: Request,
    keys: Annotated[KeyProvider, Depends(_keys)],
) -> ConnectionOut:
    """Store the workspace's Claude API key, encrypted, replacing any stored one. The
    workspace's runs on Claude use it."""
    secret = SecretStr(body.api_key.get_secret_value().strip())
    try:
        info = await put_connection(_sessions(request), keys, workspace_id, "claude", secret)
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    return ConnectionOut.of(info)


@router.delete(
    "/{workspace_id}/connections/claude",
    operation_id="deleteClaudeConnection",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"description": "No such workspace, or it has no Claude connection"}},
)
async def delete_claude(workspace_id: UUID, request: Request) -> None:
    try:
        deleted = await delete_connection(_sessions(request), workspace_id, "claude")
    except WorkspaceNotFoundError:
        raise _not_found(workspace_id) from None
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "the workspace has no Claude connection")
