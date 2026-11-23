"""Run summaries: what the runs list and a run's header show, read from the `runs` row.

The summary columns are a projection of the run's events (see `sink.summary_values`), so
listing never scans `run_events`.
"""

import base64
import binascii
import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, String, cast, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_sandbox import RepoSource
from agentic_store.models import Run
from agentic_store.sandboxes import SandboxInfo, sandbox_info


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
    # The stored workflow version the run was started from, if any.
    workflow_version: int | None
    repo: RepoSource | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    pr_url: str | None
    # When the run last became `queued`, and until when a worker holds its lease (12.1).
    queued_at: datetime
    lease_expires_at: datetime | None
    # `{node_id, title, expires_at}` of the gate the run is paused at.
    waiting_gate: dict[str, Any] | None
    rerun_of: UUID | None
    # The GitHub login whose Copilot the run uses (8.2); `None`: the run is on Claude.
    copilot_login: str | None
    # The provider the run was started on and the providers its agents use (8.3).
    provider: str
    providers: list[str]
    # `{node_id, use_wip, edited}` of a rerun from a step (12.4).
    rerun_from: dict[str, Any] | None
    # What started the run: `manual`, `api`, `rerun` or `jira` (7.3).
    trigger: str
    # The branch the run works on, if known.
    branch: str | None
    input: str
    # The Jira issue a trigger started the run on (7.3), `{cloud_id, site, key, url}`; a rerun
    # keeps it.
    jira_issue: dict[str, Any] | None
    failure_reason: str | None
    # Why a cancelled run was cancelled: by its user, or its approval expired.
    cancel_reason: str | None
    usage: "RunUsageRow"
    # How many times a writer tried to change a protected path (13.5).
    protected_attempts: int
    times: "RunTimesRow"
    # What became of the run's sandbox: kept until when, or removed (12.3).
    sandbox: SandboxInfo
    # The workflow spec the run was created with; read only for one run's detail.
    spec: dict[str, Any] | None = None
    # The copies of the workflows the spec calls (6.5), by `<id>@<version>`; with `spec`.
    subflows: dict[str, Any] | None = None
    # The Jira issue as the run's agents were told it (7.4); with `spec`.
    jira_brief: dict[str, Any] | None = None
    # The pull request review a follow-up works from (7.6): `runs.pr_review`, references only,
    # and, with `spec`, the review as its agents were told it.
    pr_review: dict[str, Any] | None = None
    pr_review_brief: dict[str, Any] | None = None
    # The spec file the run was given (7.7), without its text; with `spec`.
    spec_file: dict[str, Any] | None = None


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


@dataclass(frozen=True)
class RunTimesRow:
    """Time spent executing (`active_ms`, `None` until the run started) and paused at gates
    (`waiting_ms`), in closed stretches; the open one began at `active_since` or
    `waiting_since`."""

    active_ms: int | None
    waiting_ms: int
    active_since: datetime | None
    waiting_since: datetime | None

    def at(self, now: datetime) -> tuple[int | None, int]:
        """`(active_ms, waiting_ms)` with the open stretch counted up to `now`."""
        active, waiting = self.active_ms, self.waiting_ms
        if self.active_since is not None:
            active = (active or 0) + _ms(self.active_since, now)
        if self.waiting_since is not None:
            waiting += _ms(self.waiting_since, now)
        return active, waiting


def _ms(start: datetime, end: datetime) -> int:
    return max(0, round((end - start).total_seconds() * 1000))


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
        Run.workflow_version,
        Run.repo,
        Run.created_at,
        Run.started_at,
        Run.finished_at,
        Run.pr_url,
        Run.queued_at,
        Run.lease_expires_at,
        Run.waiting_gate,
        Run.rerun_of,
        Run.copilot_login,
        Run.provider,
        Run.providers,
        Run.rerun_from,
        Run.jira_issue,
        Run.pr_review,
        Run.trigger,
        Run.branch,
        Run.input,
        Run.failure_reason,
        Run.cancel_reason,
        Run.input_tokens,
        Run.output_tokens,
        Run.cache_read_tokens,
        Run.cache_write_tokens,
        Run.estimated_usd,
        Run.cost_complete,
        Run.protected_attempts,
        Run.policy["budget_usd"].astext.label("budget_usd"),
        Run.active_ms,
        Run.waiting_ms,
        Run.active_since,
        Run.waiting_since,
        Run.sandbox_kept_until,
        Run.sandbox_removed_at,
    )


def _summary(
    row: Any,
    *,
    spec: dict[str, Any] | None = None,
    subflows: dict[str, Any] | None = None,
    jira_brief: dict[str, Any] | None = None,
    pr_review_brief: dict[str, Any] | None = None,
    spec_file: dict[str, Any] | None = None,
) -> RunSummaryRow:
    return RunSummaryRow(
        id=row.id,
        workspace_id=row.workspace_id,
        status=row.status,
        workflow_id=row.workflow_id,
        workflow_name=row.workflow_name,
        template_id=row.template_id,
        workflow_version=row.workflow_version,
        repo=RepoSource.model_validate(row.repo) if row.repo is not None else None,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        pr_url=row.pr_url,
        queued_at=row.queued_at,
        lease_expires_at=row.lease_expires_at,
        waiting_gate=row.waiting_gate,
        rerun_of=row.rerun_of,
        copilot_login=row.copilot_login,
        provider=row.provider,
        providers=list(row.providers),
        rerun_from=row.rerun_from,
        trigger=row.trigger,
        branch=row.branch,
        jira_issue=row.jira_issue,
        input=row.input,
        failure_reason=row.failure_reason,
        cancel_reason=row.cancel_reason,
        usage=RunUsageRow(
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cache_read_tokens=row.cache_read_tokens,
            cache_write_tokens=row.cache_write_tokens,
            estimated_usd=row.estimated_usd,
            cost_complete=row.cost_complete,
            budget_usd=Decimal(row.budget_usd) if row.budget_usd is not None else None,
        ),
        protected_attempts=row.protected_attempts,
        times=RunTimesRow(
            active_ms=row.active_ms,
            waiting_ms=row.waiting_ms,
            active_since=row.active_since,
            waiting_since=row.waiting_since,
        ),
        sandbox=sandbox_info(
            row.status,
            row.sandbox_kept_until,
            row.sandbox_removed_at,
            has_repo=row.repo is not None,
        ),
        spec=spec,
        subflows=subflows,
        jira_brief=jira_brief,
        pr_review=row.pr_review,
        pr_review_brief=pr_review_brief,
        spec_file={k: v for k, v in spec_file.items() if k != "text"} if spec_file else None,
    )


def _filtered(
    query: Select[*tuple[Any, ...]],
    workspace_id: UUID,
    template_id: str | None,
    repo_url: str | None,
    search: str | None = None,
    provider: str | None = None,
) -> Select[*tuple[Any, ...]]:
    query = query.where(Run.workspace_id == workspace_id)
    if provider is not None:
        # A run matches when any of its agents used the provider (8.3).
        query = query.where(Run.providers.contains([provider]))
    if template_id is not None:
        query = query.where(Run.template_id == template_id)
    if repo_url is not None:
        query = query.where(Run.repo_url == repo_url)
    if search is not None and search.strip():
        query = query.where(_matches(search.strip()))
    return query


# Ids are shown as their first 8 characters; 4 is the shortest prefix worth matching.
_ID_PREFIX = re.compile(r"[0-9a-fA-F-]{4,36}")
_PR_NUMBER = re.compile(r"#?(\d+)")


def _matches(search: str) -> ColumnElement[bool]:
    """A run whose id starts with `search`, whose last PR is number `search` (`42` or `#42`), or
    whose workflow name contains it, ignoring case. `%` and `_` match themselves."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conditions = [Run.spec["name"].astext.ilike(f"%{escaped}%", escape="\\")]
    if _ID_PREFIX.fullmatch(search):
        conditions.append(cast(Run.id, String).like(f"{search.lower()}%"))
    if pr := _PR_NUMBER.fullmatch(search):
        conditions.append(Run.pr_url.like(f"%/pull/{int(pr.group(1))}"))
    return or_(*conditions)


@dataclass(frozen=True)
class RunCountsRow:
    """How many runs each saved view of the runs list holds."""

    all: int
    # Queued or running.
    running: int
    # Waiting at a gate that has not expired.
    waiting: int
    failed: int


async def count_runs(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    *,
    template_id: str | None = None,
    repo_url: str | None = None,
    provider: str | None = None,
) -> RunCountsRow:
    """The workspace's runs counted per saved view, with the same filters as
    `list_run_summaries`. A run waiting at a gate past its expiry no longer needs approval, so it
    is not counted as waiting even before a worker cancels it."""

    def count(condition: ColumnElement[bool]) -> Any:
        return func.count().filter(condition)

    waiting = (Run.status == "waiting") & (
        Run.gate_expires_at.is_(None) | (Run.gate_expires_at > func.now())
    )
    query = _filtered(
        select(
            func.count().label("all"),
            count(Run.status.in_(("queued", "running"))).label("running"),
            count(waiting).label("waiting"),
            count(Run.status == "failed").label("failed"),
        ),
        workspace_id,
        template_id,
        repo_url,
        provider=provider,
    )
    async with sessions() as session:
        row = (await session.execute(query)).one()
    return RunCountsRow(all=row.all, running=row.running, waiting=row.waiting, failed=row.failed)


async def list_run_summaries(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    *,
    statuses: Collection[str] = (),
    template_id: str | None = None,
    repo_url: str | None = None,
    search: str | None = None,
    provider: str | None = None,
    cursor: str | None = None,
    limit: int = 25,
) -> tuple[list[RunSummaryRow], str | None]:
    """One page of the workspace's runs, newest first, and the cursor of the next page (`None`
    on the last one). Filters combine with AND; several `statuses` match any of them; `search`
    finds a run by id prefix, PR number or workflow name; `provider` keeps the runs that
    used it (8.3). Raises `InvalidCursorError` for a
    cursor this function did not return."""
    query = _filtered(_select(), workspace_id, template_id, repo_url, search, provider)
    if statuses:
        query = query.where(Run.status.in_(statuses))
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
        query = (
            _select()
            .add_columns(Run.spec, Run.subflows, Run.jira_brief, Run.pr_review_brief, Run.spec_file)
            .where(Run.id == run_id)
        )
        row = (await session.execute(query)).one_or_none()
    if row is None:
        return None
    return _summary(
        row,
        spec=row.spec,
        subflows=row.subflows,
        jira_brief=row.jira_brief,
        pr_review_brief=row.pr_review_brief,
        spec_file=row.spec_file,
    )
