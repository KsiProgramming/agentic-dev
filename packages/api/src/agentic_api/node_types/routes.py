from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.nodes import NODE_MANIFESTS, NodeManifest, composite_manifest
from agentic_store import Workspace, list_composites

router = APIRouter(prefix="/node-types", tags=["node-types"])


@router.get(
    "",
    operation_id="listNodeTypes",
    responses={404: {"description": "No workspace with this id"}},
)
async def list_node_types(
    request: Request,
    workspace_id: Annotated[
        UUID | None,
        Query(description="Add this workspace's composites after the primitives (6.6)."),
    ] = None,
) -> list[NodeManifest]:
    """Every primitive's manifest, in palette order: the builder draws its palette and cards
    from them, so a primitive the engine knows needs no web change. With `workspace_id`, each of
    the workspace's composites follows, by name (category `workspace`): a `subflow` that calls
    its latest published version."""
    manifests = list(NODE_MANIFESTS)
    if workspace_id is None:
        return manifests
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"workspace {workspace_id} not found")
    composites = await list_composites(sessions, workspace_id)
    return manifests + [
        composite_manifest(c.workflow_id, c.version, c.name, c.description) for c in composites
    ]
