"""Pull request review feedback (7.6): the GitHub deliveries received, the run a review comment
follows up, and the checks that keep follow-ups on one pull request one at a time and bounded.

A follow-up is a rerun from a step (12.4) of the latest run on the pull request, created by
`agentic_store.rerun.create_rerun` with a `FollowUp`; `check_follow_up` runs in its transaction,
under a lock on the pull request, so two comments at once start one follow-up."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import PR_OPENED
from agentic_engine.spec import WorkflowSpec
from agentic_store.audit import audit
from agentic_store.cancel import ENDED_STATUSES
from agentic_store.connections import GITHUB
from agentic_store.models import Connection, GithubDelivery, Run, RunEventRow
from agentic_store.subflows import run_spec

DELIVERY_RETENTION: Final = timedelta(days=30)

type IgnoreReason = Literal[
    "not_allowed", "no_run", "not_enabled", "busy", "limit", "pr_closed", "no_head", "start_failed"
]
"""Why a `@<app> fix this` comment started nothing. `no_head`: the run before published nothing
the follow-up can push onto (no `pr_opened` with a commit). `start_failed`: the rerun was refused
(the step cannot be restored, the workflow is above the limits)."""


class ReviewBusyError(Exception):
    """A run on the pull request has not ended yet."""


class ReviewLimitError(Exception):
    """The pull request had `review_rounds` follow-ups already."""


@dataclass(frozen=True)
class PrRun:
    """The latest run on a pull request, and what it pushed there (its last `pr_opened`)."""

    id: UUID
    workspace_id: UUID
    status: str
    spec: WorkflowSpec
    head_branch: str | None
    head_sha: str | None
    pushed_at: datetime | None


@dataclass(frozen=True)
class FollowUp:
    """What makes a rerun a follow-up of a pull request review: the `pr_review` it keeps, and
    the workspace's `review_rounds` when it is created."""

    pr_review: dict[str, JsonValue]
    review_rounds: int

    @property
    def pr_url(self) -> str:
        return str(self.pr_review["pr_url"])


async def record_github_delivery(
    sessions: async_sessionmaker[AsyncSession], delivery_id: str, event: str
) -> bool:
    """Record a delivery; `False` when it was recorded already (a redelivery)."""
    async with sessions.begin() as session:
        inserted = await session.scalar(
            pg_insert(GithubDelivery)
            .values(delivery_id=delivery_id[:64], event=event[:64])
            .on_conflict_do_nothing(index_elements=["delivery_id"])
            .returning(GithubDelivery.delivery_id)
        )
    return inserted is not None


async def set_github_delivery_outcome(
    sessions: async_sessionmaker[AsyncSession], delivery_id: str, outcome: str
) -> None:
    async with sessions.begin() as session:
        await session.execute(
            update(GithubDelivery)
            .where(GithubDelivery.delivery_id == delivery_id[:64])
            .values(outcome=outcome[:32])
        )


async def prune_github_deliveries(
    sessions: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> int:
    """Delete deliveries older than `DELIVERY_RETENTION`; how many."""
    now = now or datetime.now(UTC)
    async with sessions.begin() as session:
        result = await session.execute(
            delete(GithubDelivery).where(GithubDelivery.received_at < now - DELIVERY_RETENTION)
        )
    return int(getattr(result, "rowcount", 0) or 0)


async def github_workspaces(
    sessions: async_sessionmaker[AsyncSession], installation_id: int
) -> list[UUID]:
    """The workspaces linked to the GitHub App installation."""
    async with sessions() as session:
        rows = await session.scalars(
            select(Connection.workspace_id)
            .where(Connection.provider == GITHUB, Connection.external_id == installation_id)
            .order_by(Connection.workspace_id)
        )
        return list(rows)


async def latest_pr_run(
    sessions: async_sessionmaker[AsyncSession], workspace_ids: list[UUID], pr_url: str
) -> PrRun | None:
    """The latest run of `workspace_ids` that published to `pr_url` (the original or the last
    follow-up that pushed), with the branch and commit of its last `pr_opened`."""
    if not workspace_ids:
        return None
    async with sessions() as session:
        run = await session.scalar(
            select(Run)
            .where(Run.workspace_id.in_(workspace_ids), Run.pr_url == pr_url)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(1)
        )
        if run is None:
            return None
        opened = await session.scalar(
            select(RunEventRow)
            .where(RunEventRow.run_id == run.id, RunEventRow.type == PR_OPENED)
            .order_by(RunEventRow.seq.desc())
            .limit(1)
        )
    payload = opened.payload if opened is not None else {}
    head, commit = payload.get("head"), payload.get("commit")
    return PrRun(
        id=run.id,
        workspace_id=run.workspace_id,
        status=run.status,
        spec=run_spec(run.spec, run.subflows),
        head_branch=head if isinstance(head, str) and head else None,
        head_sha=commit if isinstance(commit, str) and len(commit) == 40 else None,
        pushed_at=opened.created_at if opened is not None else None,
    )


async def pr_busy(sessions: async_sessionmaker[AsyncSession], pr_url: str) -> bool:
    """Whether a run on the pull request (one that published to it, or a follow-up of it) has
    not ended."""
    async with sessions() as session:
        return await _busy(session, pr_url)


async def check_follow_up(session: AsyncSession, follow_up: FollowUp) -> None:
    """In the transaction creating a follow-up: lock the pull request until it commits, then
    raise `ReviewBusyError` if a run on it has not ended, or `ReviewLimitError` if it had
    `review_rounds` follow-ups already."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 76))"), {"key": follow_up.pr_url}
    )
    if await _busy(session, follow_up.pr_url):
        raise ReviewBusyError(f"a run on {follow_up.pr_url} has not ended")
    rounds = await session.scalar(
        select(func.count())
        .select_from(Run)
        .where(Run.pr_review.is_not(None), Run.pr_review["pr_url"].astext == follow_up.pr_url)
    )
    if (rounds or 0) >= follow_up.review_rounds:
        raise ReviewLimitError(
            f"{follow_up.pr_url} had {rounds} follow-ups, the most the workspace allows"
        )


async def audit_review_ignored(
    sessions: async_sessionmaker[AsyncSession],
    workspace_ids: list[UUID],
    reason: IgnoreReason,
    details: dict[str, JsonValue],
    run_id: UUID | None = None,
) -> None:
    """`github.review_ignored` in each workspace the delivery could be for, with the reason."""
    if not workspace_ids:
        return
    async with sessions.begin() as session:
        for workspace_id in workspace_ids:
            audit(
                session,
                workspace_id,
                "github.review_ignored",
                actor_type="system",
                run_id=run_id,
                details={**details, "reason": reason},
            )


async def set_run_pr_review_brief(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, brief: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Store the review brief of a follow-up (7.6), unless one is stored already; the stored
    one, so every attempt tells its agents the same review."""
    async with sessions.begin() as session:
        run = await session.get_one(Run, run_id, with_for_update=True)
        if run.pr_review_brief is None:
            run.pr_review_brief = brief
        return run.pr_review_brief


async def _busy(session: AsyncSession, pr_url: str) -> bool:
    found = await session.scalar(
        select(Run.id)
        .where(
            or_(
                Run.pr_url == pr_url,
                Run.pr_review["pr_url"].astext == pr_url,
            ),
            Run.status.not_in(list(ENDED_STATUSES)),
        )
        .limit(1)
    )
    return found is not None


__all__ = [
    "DELIVERY_RETENTION",
    "FollowUp",
    "IgnoreReason",
    "PrRun",
    "ReviewBusyError",
    "ReviewLimitError",
    "audit_review_ignored",
    "check_follow_up",
    "github_workspaces",
    "latest_pr_run",
    "pr_busy",
    "prune_github_deliveries",
    "record_github_delivery",
    "set_github_delivery_outcome",
    "set_run_pr_review_brief",
]
