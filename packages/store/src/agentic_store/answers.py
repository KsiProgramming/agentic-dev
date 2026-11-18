"""Answers to a question a run asked (7.9): a run paused at a `wait_for` is continued when the
platform finds an answer, never by a person's decision (`record_approval` refuses one).

The step's `gate_waiting` event says which issue it waits on and after which comment
(`wait_for`), and the event sink keeps it in `runs.waiting_gate`. Either route that finds an
answer (the comment webhook, a direct check) calls `answer_arrived`: it records an approval by
`ANSWER_DECIDER` and queues the run, once; a second call finds the step decided and does
nothing. The expiry sweep (`agentic_store.expiry`) ends an unanswered wait.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.approvals import _approval, _last_gate_waiting, _now, _pass  # pyright: ignore
from agentic_store.audit import audit
from agentic_store.models import Approval, Run

ANSWER_DECIDER: Final = "jira:comment"
"""`decided_by` of the approval that continues a wait."""


@dataclass(frozen=True)
class WaitingRun:
    """A run paused at a `wait_for`: what a check needs to look for its answer."""

    run_id: UUID
    workspace_id: UUID
    node_id: str
    cloud_id: str
    issue_key: str
    after_comment_id: str


def _waiting(run: Run) -> WaitingRun | None:
    gate = run.waiting_gate or {}
    wait = gate.get("wait_for")
    issue = run.jira_issue or {}
    if not isinstance(wait, dict) or not isinstance(node := gate.get("node_id"), str):
        return None
    after = wait.get("after_comment_id")
    where = wait.get("issue")
    key = where.get("key") if isinstance(where, dict) else None
    cloud = issue.get("cloud_id")
    if not (isinstance(after, str) and isinstance(key, str) and isinstance(cloud, str)):
        return None
    return WaitingRun(run.id, run.workspace_id, node, cloud, key.upper(), after)


async def waiting_runs(
    sessions: async_sessionmaker[AsyncSession],
    *,
    issue_key: str | None = None,
    cloud_id: str | None = None,
    workspace_id: UUID | None = None,
    run_id: UUID | None = None,
) -> list[WaitingRun]:
    """The runs paused at a `wait_for` that has not expired, narrowed by the issue, its site, the
    workspace or the run."""
    query = select(Run).where(
        Run.status == "waiting",
        Run.waiting_gate["wait_for"].is_not(None),
        (Run.gate_expires_at.is_(None)) | (Run.gate_expires_at > func.now()),
    )
    if workspace_id is not None:
        query = query.where(Run.workspace_id == workspace_id)
    if run_id is not None:
        query = query.where(Run.id == run_id)
    if cloud_id is not None:
        query = query.where(Run.jira_issue["cloud_id"].astext == cloud_id)
    async with sessions() as session:
        rows = (await session.scalars(query)).all()
    found = [w for row in rows if (w := _waiting(row)) is not None]
    return [w for w in found if issue_key is None or w.issue_key == issue_key.upper()]


async def answer_arrived(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, node_id: str
) -> bool:
    """Continue the run waiting at `node_id` because it was answered, and queue it; the caller
    enqueues it. `True` if this call did it, `False` if the run is no longer waiting there (a
    second route got there first, it expired, or it ended)."""
    try:
        async with sessions.begin() as session:
            run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None or run.status != "waiting":
                return False
            if run.gate_expires_at is not None and run.gate_expires_at <= await _now(session):
                return False
            row = await _last_gate_waiting(session, run_id)
            if row is None or row[0] != node_id or not row[1].get("wait_for"):
                return False
            iteration = await _pass(session, run_id, node_id)
            if await _approval(session, run_id, node_id, iteration) is not None:
                return False
            session.add(
                Approval(
                    run_id=run_id,
                    node_id=node_id,
                    iteration=iteration,
                    decision="approve",
                    decided_by=ANSWER_DECIDER,
                )
            )
            await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    status="queued",
                    worker_id=None,
                    lease_expires_at=None,
                    attempt=0,
                    queued_at=func.now(),
                )
            )
            details: dict[str, JsonValue] = {"answered": True, "by": ANSWER_DECIDER}
            audit(
                session,
                run.workspace_id,
                "gate.approved",
                actor_type="system",
                run_id=run_id,
                node_id=node_id,
                details=details,
            )
    except IntegrityError:
        return False
    return True
