"""Run summaries: what the runs list and a run's header show, read from the `runs` row.

The summary columns are a projection of the run's events (see `sink.summary_values`), so
listing never scans `run_events`.
"""

import base64
import binascii
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_sandbox import RepoSource
from agentic_store.models import Run


class InvalidCursorError(ValueError):
    """A page cursor that `list_run_summaries` did not hand out."""


@dataclass(frozen=True)
class RunSummaryRow:
    id: UUID
    workspace_id: UUID
    status: str
    workflow_id: str
    workflow_name: str
    template_id: str | None
    repo: RepoSource | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    pr_url: str | None
    # `{node_id, title}` of the gate the run is paused at.
    waiting_gate: dict[str, Any] | None
    rerun_of: UUID | None
    input: str
    failure_reason: str | None
    usage: "RunUsageRow"


@dataclass(frozen=True)
class RunUsageRow:
    """Totals of the run's `usage` events. `cost_complete` is false once one had no price, and
    `estimated_usd` is then a lower bound."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    estimated_usd: Decimal
    cost_complete: bool
    # The run's budget, frozen in its policy; `None` is no budget.
    budget_usd: Decimal | None = None


def encode_cursor(created_at: datetime, run_id: UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(run_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        created_at, run_id = json.loads(raw)
        return datetime.fromisoformat(created_at), UUID(run_id)
    except (binascii.Error, ValueError, TypeError) as e:
        raise InvalidCursorError(f"invalid cursor {cursor!r}") from e


def _select() -> Select[*tuple[Any, ...]]:
    return select(
        Run.id,
        Run.workspace_id,
        Run.status,
        Run.spec["id"].astext.label("workflow_id"),
        Run.spec["name"].astext.label("workflow_name"),
        Run.template_id,
        Run.repo,
        Run.created_at,
        Run.started_at,
        Run.finished_at,
        Run.pr_url,
        Run.waiting_gate,
        Run.rerun_of,
        Run.input,
        Run.failure_reason,
        Run.input_tokens,
        Run.output_tokens,
        Run.cache_read_tokens,
        Run.cache_write_tokens,
        Run.estimated_usd,
        Run.cost_complete,
        Run.policy["budget_usd"].astext.label("budget_usd"),
    )


def _summary(row: Any) -> RunSummaryRow:
    return RunSummaryRow(
        id=row.id,
        workspace_id=row.workspace_id,
        status=row.status,
        workflow_id=row.workflow_id,
        workflow_name=row.workflow_name,
        template_id=row.template_id,
        repo=RepoSource.model_validate(row.repo) if row.repo is not None else None,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        pr_url=row.pr_url,
        waiting_gate=row.waiting_gate,
        rerun_of=row.rerun_of,
        input=row.input,
        failure_reason=row.failure_reason,
        usage=RunUsageRow(
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cache_read_tokens=row.cache_read_tokens,
            cache_write_tokens=row.cache_write_tokens,
            estimated_usd=row.estimated_usd,
            cost_complete=row.cost_complete,
            budget_usd=Decimal(row.budget_usd) if row.budget_usd is not None else None,
        ),
    )


async def list_run_summaries(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    *,
    statuses: Collection[str] = (),
    template_id: str | None = None,
    repo_url: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> tuple[list[RunSummaryRow], str | None]:
    """One page of the workspace's runs, newest first, and the cursor of the next page (`None`
    on the last one). Filters combine with AND; several `statuses` match any of them. Raises
    `InvalidCursorError` for a cursor this function did not return."""
    query = _select().where(Run.workspace_id == workspace_id)
    if statuses:
        query = query.where(Run.status.in_(statuses))
    if template_id is not None:
        query = query.where(Run.template_id == template_id)
    if repo_url is not None:
        query = query.where(Run.repo_url == repo_url)
    if cursor is not None:
        query = query.where(tuple_(Run.created_at, Run.id) < tuple_(*decode_cursor(cursor)))
    # One more than a page tells whether there is a next one.
    query = query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1)
    async with sessions() as session:
        rows = [_summary(row) for row in await session.execute(query)]
    if len(rows) <= limit:
        return rows, None
    last = rows[limit - 1]
    return rows[:limit], encode_cursor(last.created_at, last.id)


async def list_changed_run_summaries(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, *, since: datetime
) -> list[tuple[datetime, RunSummaryRow]]:
    """The workspace's runs whose summary changed after `since`, with when it last changed,
    oldest change first. `updated_at` moves only with events that change the summary, so a
    streamed text delta does not list its run again."""
    query = (
        _select()
        .add_columns(Run.updated_at)
        .where(Run.workspace_id == workspace_id, Run.updated_at > since)
        .order_by(Run.updated_at, Run.id)
    )
    async with sessions() as session:
        return [(row.updated_at, _summary(row)) for row in await session.execute(query)]


async def get_run_summary(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID
) -> RunSummaryRow | None:
    async with sessions() as session:
        row = (await session.execute(_select().where(Run.id == run_id))).one_or_none()
    return None if row is None else _summary(row)
