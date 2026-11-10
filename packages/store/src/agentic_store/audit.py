"""The audit log: one append-only row per action in a workspace (`audit_log` lists them).

Every writer adds its row with `audit` to the session of the change it records, so the row is
committed with the change or not at all. `details` says what changed for people to read; it
never holds file contents or secrets (edited paths, not edits; key hints, not keys).
"""

from datetime import datetime
from decimal import Decimal
from typing import Final, Literal, get_args
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from agentic_store.models import AuditEvent

AuditAction = Literal[
    "run.created",
    "run.rerun",
    "run.cancel_requested",
    "run.ended",
    "repo.created",
    "gate.approved",
    "gate.rejected",
    "gate.expired",
    "connection.added",
    "connection.removed",
    "policy.updated",
    "pricing.updated",
    "workflow.created",
    "workflow.updated",
    "workflow.restored",
    "workflow.published",
]
AUDIT_ACTIONS: Final[tuple[AuditAction, ...]] = get_args(AuditAction)

ActorType = Literal["user", "system"]


def audit(
    session: AsyncSession,
    workspace_id: UUID,
    action: AuditAction,
    *,
    actor_type: ActorType = "user",
    run_id: UUID | None = None,
    node_id: str | None = None,
    details: dict[str, JsonValue] | None = None,
    at: datetime | None = None,
) -> None:
    """Add an audit row to `session`, committed with the change it records. `at` defaults to
    the transaction's time."""
    row = AuditEvent(
        workspace_id=workspace_id,
        action=action,
        actor_type=actor_type,
        run_id=run_id,
        node_id=node_id,
        details=details or {},
    )
    if at is not None:
        row.at = at
    session.add(row)


def usd(amount: Decimal | None) -> str | None:
    """A USD amount as `details` holds it: a decimal string, so it is never rounded."""
    return None if amount is None else str(amount)
