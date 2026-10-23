"""A workspace's model prices: the list prices (`agentic_runtime.DEFAULT_PRICES`) with the
workspace's overrides on top. Runs are priced with them when their usage is logged, so changing
a price never changes the cost of a past run."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_runtime import DEFAULT_PRICES, ModelPrice, PriceTable
from agentic_store.connections import WorkspaceNotFoundError
from agentic_store.models import Workspace, WorkspaceModelPrice


async def list_price_overrides(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> dict[str, ModelPrice]:
    """The workspace's overrides by model, sorted by model. Raises `WorkspaceNotFoundError`."""
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        rows = await session.scalars(
            select(WorkspaceModelPrice)
            .where(WorkspaceModelPrice.workspace_id == workspace_id)
            .order_by(WorkspaceModelPrice.model)
        )
        return {row.model: _price(row) for row in rows}


async def replace_price_overrides(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    overrides: Mapping[str, ModelPrice],
) -> None:
    """Make `overrides` the workspace's only overrides; an empty mapping resets every model to
    its list price. Raises `WorkspaceNotFoundError`."""
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        workspace = await session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        await session.execute(
            delete(WorkspaceModelPrice).where(WorkspaceModelPrice.workspace_id == workspace_id)
        )
        session.add_all(
            WorkspaceModelPrice(
                workspace_id=workspace_id,
                model=model,
                **price.model_dump(),
                updated_at=now,
            )
            for model, price in overrides.items()
        )


async def workspace_price_table(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> PriceTable:
    """The prices the workspace's runs use. Raises `WorkspaceNotFoundError`."""
    return DEFAULT_PRICES.with_overrides(await list_price_overrides(sessions, workspace_id))


def _price(row: WorkspaceModelPrice) -> ModelPrice:
    return ModelPrice(
        input=row.input,
        output=row.output,
        cache_write_5m=row.cache_write_5m,
        cache_write_1h=row.cache_write_1h,
        cache_read=row.cache_read,
    )
