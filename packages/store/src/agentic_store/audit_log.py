"""Listing a workspace's audit log, newest first (`audit` writes it)."""

import base64
import binascii
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.connections import WorkspaceNotFoundError
from agentic_store.models import AuditEvent, Run, Workspace
from agentic_store.summaries import InvalidCursorError


@dataclass(frozen=True)
class AuditRunRef:
    """What the audit page shows of an entry's run, as it is now."""

    template_id: str | None
    repo_url: str | None
    status: str


@dataclass(frozen=True)
class AuditEventRow:
    id: int
    at: datetime
    action: str
    actor_type: str
    actor_id: str | None
    run_id: UUID | None
    node_id: str | None
    details: dict[str, JsonValue]
    run: AuditRunRef | None


async def list_audit_events(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    *,
    limit: int = 50,
    cursor: str | None = None,
    actions: Collection[str] = (),
    run_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[AuditEventRow], str | None]:
    """One page of the workspace's audit log, newest first, and the cursor of the next page
    (`None` on the last). `since` is inclusive, `until` exclusive. Raises
    `WorkspaceNotFoundError`, or `InvalidCursorError` for a cursor this function did not return."""
    query = (
        select(AuditEvent, Run.template_id, Run.repo_url, Run.status)
        .outerjoin(Run, Run.id == AuditEvent.run_id)
        .where(AuditEvent.workspace_id == workspace_id)
        .order_by(AuditEvent.at.desc(), AuditEvent.id.desc())
        .limit(limit + 1)
    )
    if actions:
        query = query.where(AuditEvent.action.in_(actions))
    if run_id is not None:
        query = query.where(AuditEvent.run_id == run_id)
    if since is not None:
        query = query.where(AuditEvent.at >= since)
    if until is not None:
        query = query.where(AuditEvent.at < until)
    if cursor is not None:
        query = query.where(tuple_(AuditEvent.at, AuditEvent.id) < tuple_(*_decode(cursor)))
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        rows = (await session.execute(query)).all()
    items = [_row(*row) for row in rows[:limit]]
    if len(rows) <= limit:
        return items, None
    last = items[-1]
    return items, _encode(last.at, last.id)


def _row(
    event: AuditEvent, template_id: str | None, repo_url: str | None, status: str | None
) -> AuditEventRow:
    return AuditEventRow(
        id=event.id,
        at=event.at,
        action=event.action,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        run_id=event.run_id,
        node_id=event.node_id,
        details=event.details,
        run=None if status is None else AuditRunRef(template_id, repo_url, status),
    )


def _encode(at: datetime, event_id: int) -> str:
    raw = json.dumps([at.isoformat(), event_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        at, event_id = json.loads(raw)
        if not isinstance(event_id, int):
            raise TypeError(event_id)
        return datetime.fromisoformat(at), event_id
    except (binascii.Error, ValueError, TypeError) as e:
        raise InvalidCursorError(f"invalid cursor {cursor!r}") from e
