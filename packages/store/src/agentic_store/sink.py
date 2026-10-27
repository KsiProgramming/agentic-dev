"""Persists a run's event stream to Postgres."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    DateTime,
    case,
    cast,
    false,
    func,
    literal,
    null,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import (
    GATE_DECIDED,
    GATE_WAITING,
    NODE_FAILED,
    PR_OPENED,
    REPO_CREATED,
    RUN_END_STATUS,
    RUN_FAILED,
    RUN_RESUMED,
    RUN_STARTED,
    RunEvent,
    RunStatus,
)
from agentic_runtime import Usage
from agentic_store.audit import audit, usd
from agentic_store.models import AuditEvent, Run, RunEventRow

USAGE: Final = "usage"

RUN_EVENTS_CHANNEL = "run_events"
"""Postgres `NOTIFY` channel; the payload of each notification is `<run_id>:<seq>`."""

RUN_STATUS: dict[str, RunStatus] = {
    RUN_STARTED: "running",
    RUN_RESUMED: "running",
    GATE_WAITING: "waiting",
}
"""The run status each non-final event sets; the final ones are `RUN_END_STATUS`."""


def summary_values(event: RunEvent) -> dict[str, Any]:
    """The `runs` columns an event sets, beyond `updated_at`:

    | Event | Sets |
    |---|---|
    | `run_started` | `status=running`, `started_at` (the first start only) |
    | `run_resumed` | `status=running`, `waiting_gate=null` |
    | `gate_waiting` | `status=waiting`, `waiting_gate={node_id, title}` |
    | `gate_decided` | `waiting_gate=null` |
    | `pr_opened` | `pr_url` (the last one wins) |
    | `node_failed` with an `error` | `failure_reason="node <id>: <error>"` |
    | `run_completed`, `run_cancelled` | end status, `finished_at`; clears the gate and reason |
    | `run_failed` | `failed`, `finished_at`, clears `waiting_gate`; `failure_reason` = `error` |
    | `usage` | adds its tokens and `estimated_usd`; `cost_complete=false` if it has no price |

    and the time columns (see `time_values`).
    """
    values: dict[str, Any] = {}
    if status := RUN_STATUS.get(event.type) or RUN_END_STATUS.get(event.type):
        values["status"] = status
    payload = event.payload
    if event.type == USAGE and isinstance(usage := event.agent_event(), Usage):
        return _usage_values(usage)
    values.update(time_values(event))
    if event.type == RUN_STARTED:
        values["started_at"] = func.coalesce(Run.started_at, event.created_at)
    elif event.type in (RUN_RESUMED, GATE_DECIDED):
        values["waiting_gate"] = null()  # SQL NULL, not JSON null
    elif event.type == GATE_WAITING:
        title = payload.get("title")
        values["waiting_gate"] = {
            "node_id": event.node_id,
            "title": title if isinstance(title, str) else None,
        }
    elif event.type == PR_OPENED and isinstance(url := payload.get("url"), str):
        values["pr_url"] = url
    elif (
        event.type == NODE_FAILED
        and event.node_id is not None
        and isinstance(error := payload.get("error"), str)
    ):
        values["failure_reason"] = f"node {event.node_id}: {error}"
    if event.type in RUN_END_STATUS:
        values["finished_at"] = event.created_at
        values["waiting_gate"] = null()  # SQL NULL, not JSON null
        if event.type == RUN_FAILED:
            if isinstance(error := payload.get("error"), str):
                values["failure_reason"] = error
        else:
            values["failure_reason"] = None
    return values


def time_values(event: RunEvent) -> dict[str, Any]:
    """How long the run has spent executing (`active_ms`) and paused at gates (`waiting_ms`),
    added up in stretches; `active_since` or `waiting_since` is the start of the open one.

    | Event | Closes | Opens |
    |---|---|---|
    | started, resumed | waiting; active to its last event (a cut-off attempt) | active |
    | `gate_waiting` | active | waiting (the first gate's, if two wait at once) |
    | end events | whichever is open | none |

    The gap between a cut-off attempt's last event and the next attempt counts as neither.
    A run that ends before it started keeps `active_ms` null."""
    at = literal(event.created_at, DateTime(timezone=True))
    if event.type in (RUN_STARTED, RUN_RESUMED):
        last = (
            select(func.max(RunEventRow.created_at))
            .where(RunEventRow.run_id == event.run_id, RunEventRow.seq < event.seq)
            .scalar_subquery()
        )
        return {
            "active_ms": func.coalesce(Run.active_ms, 0)
            + func.coalesce(_ms(Run.active_since, last), 0),
            "waiting_ms": Run.waiting_ms + func.coalesce(_ms(Run.waiting_since, at), 0),
            "active_since": at,
            "waiting_since": None,
        }
    if event.type == GATE_WAITING:
        return {
            "active_ms": _closed(Run.active_ms, Run.active_since, at),
            "active_since": None,
            "waiting_since": func.coalesce(Run.waiting_since, at),
        }
    if event.type in RUN_END_STATUS:
        return {
            "active_ms": _closed(Run.active_ms, Run.active_since, at),
            "waiting_ms": Run.waiting_ms + func.coalesce(_ms(Run.waiting_since, at), 0),
            "active_since": None,
            "waiting_since": None,
        }
    return {}


def _ms(start: Any, end: Any) -> ColumnElement[int]:
    """Milliseconds from `start` to `end`; null if either is."""
    return cast(func.round(func.extract("epoch", end - start) * 1000), BigInteger)


def _closed(total: Any, since: Any, at: ColumnElement[datetime]) -> ColumnElement[int | None]:
    """`total` with the stretch open since `since` closed at `at`; unchanged with none open."""
    return case((since.is_(None), total), else_=func.coalesce(total, 0) + _ms(since, at))


def _usage_values(usage: Usage) -> dict[str, Any]:
    """Increments in SQL, so concurrent map items never lose each other's usage."""
    values: dict[str, Any] = {
        "input_tokens": Run.input_tokens + usage.input_tokens,
        "output_tokens": Run.output_tokens + usage.output_tokens,
        "cache_read_tokens": Run.cache_read_tokens + usage.cache_read_tokens,
        "cache_write_tokens": Run.cache_write_tokens + usage.cache_write_tokens,
    }
    if usage.estimated_usd is None:
        values["cost_complete"] = false()
    else:
        values["estimated_usd"] = Run.estimated_usd + Decimal(str(usage.estimated_usd))
    return values


class PostgresEventSink:
    """An `EventSink` that writes each event in its own transaction, so a live run is visible
    while it runs, and notifies `RUN_EVENTS_CHANNEL` when that transaction commits.

    The run's row must exist (see `create_run`). In the same transaction each event updates the
    run's summary columns (see `summary_values`): `run_started` and `run_resumed` set it to
    `running`, `gate_waiting` to `waiting`, and the final run event sets its end status and adds
    the run's `run.ended` audit entry. The run's first `repo_created` adds `repo.created`."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def emit(self, event: RunEvent) -> None:
        async with self._sessions.begin() as session:
            session.add(
                RunEventRow(
                    run_id=event.run_id,
                    seq=event.seq,
                    type=event.type,
                    node_id=event.node_id,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )
            if values := summary_values(event):
                await session.execute(
                    update(Run)
                    .where(Run.id == event.run_id)
                    .values(**values, updated_at=event.created_at)
                )
            if event.type in RUN_END_STATUS:
                await _audit_end(session, event)
            elif event.type == REPO_CREATED:
                await _audit_repo_created(session, event)
            # Delivered on commit, so a listener that wakes up can already read the row.
            await session.execute(
                select(func.pg_notify(RUN_EVENTS_CHANNEL, f"{event.run_id}:{event.seq}"))
            )


async def _audit_end(session: AsyncSession, event: RunEvent) -> None:
    """The `run.ended` audit entry, from the run's summary as the end event left it."""
    run = await session.get(Run, event.run_id)
    if run is None:
        return
    audit(
        session,
        run.workspace_id,
        "run.ended",
        actor_type="system",
        run_id=run.id,
        at=event.created_at,
        details={
            "status": run.status,
            "failure_reason": run.failure_reason,
            "pr_url": run.pr_url,
            "estimated_usd": usd(run.estimated_usd),
            "cost_complete": run.cost_complete,
        },
    )


async def _audit_repo_created(session: AsyncSession, event: RunEvent) -> None:
    """The `repo.created` audit entry, once per run: a retried node that finds the repo its
    run created logs `repo_created` again."""
    run = await session.get(Run, event.run_id)
    if run is None:
        return
    logged = await session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.run_id == run.id, AuditEvent.action == "repo.created"
        )
    )
    if logged is not None:
        return
    payload = event.payload
    audit(
        session,
        run.workspace_id,
        "repo.created",
        actor_type="system",
        run_id=run.id,
        node_id=event.node_id,
        at=event.created_at,
        details={"full_name": payload.get("full_name"), "private": payload.get("private")},
    )


async def repo_created(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> bool:
    """Whether the run has created its repo (logged `repo_created`), so it can be cloned."""
    async with sessions() as session:
        found = await session.scalar(
            select(RunEventRow.seq)
            .where(RunEventRow.run_id == run_id, RunEventRow.type == REPO_CREATED)
            .limit(1)
        )
    return found is not None


async def max_event_seq(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> int:
    """The `seq` of the run's last event, 0 if it has none; a resumed attempt carries on after."""
    async with sessions() as session:
        last = await session.scalar(
            select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id)
        )
    return last or 0


async def list_run_events(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, *, after_seq: int = 0
) -> list[RunEvent]:
    """A run's events with `seq > after_seq`, in order."""
    async with sessions() as session:
        rows = await session.scalars(
            select(RunEventRow)
            .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
            .order_by(RunEventRow.seq)
        )
        return [
            RunEvent.model_validate(
                {
                    "run_id": row.run_id,
                    "seq": row.seq,
                    "type": row.type,
                    "node_id": row.node_id,
                    "payload": row.payload,
                    "created_at": row.created_at,
                }
            )
            for row in rows
        ]
