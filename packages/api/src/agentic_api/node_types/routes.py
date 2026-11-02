from fastapi import APIRouter

from agentic_engine.nodes import NODE_MANIFESTS, NodeManifest

router = APIRouter(prefix="/node-types", tags=["node-types"])


@router.get("", operation_id="listNodeTypes")
async def list_node_types() -> list[NodeManifest]:
    """Every primitive's manifest, in palette order: the builder draws its palette and cards
    from them, so a primitive the engine knows needs no web change."""
    return list(NODE_MANIFESTS)
