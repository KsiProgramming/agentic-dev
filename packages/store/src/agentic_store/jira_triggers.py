"""Jira triggers (7.3): the rules that start a run when an issue moves to a status or gets a
label, and what the receiver records about each delivery.

A delivery is recorded once per workspace (`record_jira_delivery`: its id is unique, so a retry
of it is dropped), then either stops there (`project_not_allowed`, `own_change`, `no_match`) or
is tried against the rules it matches; what each rule did is a fire (`started`, recorded with
its run by `create_run`; `already_running`; `start_failed`).

Rules and matching never see the issue's text: the receiver passes only the project, the
status an update moved to and the labels it added (`agentic_jira.IssueEvent`)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import Select, delete, func, select, text
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_store.audit import audit
from agentic_store.models import (
    JiraDelivery,
    JiraOwnMove,
    JiraTrigger,
    JiraTriggerFire,
    JiraWebhook,
    Run,
)

TriggerOn = Literal["status", "label"]
FireOutcome = Literal["started", "already_running", "start_failed"]
DeliveryOutcome = Literal["matched", "project_not_allowed", "own_change", "no_match"]

OWN_MOVE_WINDOW = timedelta(minutes=10)
"""How long a run's own move keeps the delivery it causes from starting a run."""
DELIVERY_RETENTION = timedelta(days=30)
ACTIVE_STATUSES = ("queued", "running", "waiting")


class JiraTriggerNotFoundError(LookupError):
    """No such rule in the workspace."""


class TriggerRunActiveError(RuntimeError):
    """The rule already has a queued, running or waiting run on the issue."""

    def __init__(self, run_id: UUID) -> None:
        super().__init__(f"run {run_id} is still going on this issue")
        self.run_id = run_id


@dataclass(frozen=True)
class JiraTriggerFields:
    """What a rule says. Exactly one of `template_id` and `workflow_id` is set."""

    cloud_id: str
    project_key: str
    on: TriggerOn
    value: str
    template_id: str | None = None
    workflow_id: str | None = None
    workflow_version: int | None = None
    repo_url: str | None = None
    ref: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class JiraTriggerFireInfo:
    at: datetime
    outcome: str
    issue_key: str
    run_id: UUID | None
    reason: str | None


@dataclass(frozen=True)
class JiraTriggerInfo:
    id: UUID
    workspace_id: UUID
    fields: JiraTriggerFields
    created_at: datetime
    updated_at: datetime
    last: JiraTriggerFireInfo | None


@dataclass(frozen=True)
class JiraOrigin:
    """Why `create_run` starts a run: a rule, the delivery it matched and the issue
    (`{cloud_id, site, key, url}`)."""

    trigger_id: UUID
    delivery_row: int | None
    delivery_id: str
    issue: dict[str, JsonValue]

    @property
    def issue_key(self) -> str:
        return str(self.issue["key"])


def trigger_matches(
    on: str, value: str, *, status_to: str | None, labels_added: Sequence[str]
) -> bool:
    """Whether a rule matches an event: the status it moved to, or one of the labels it added,
    is `value`, compared without regard to case."""
    wanted = value.strip().casefold()
    if on == "status":
        return status_to is not None and status_to.strip().casefold() == wanted
    if on == "label":
        return any(label.casefold() == wanted for label in labels_added)
    return False


# --- rules -----------------------------------------------------------------------------------


async def list_jira_triggers(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> list[JiraTriggerInfo]:
    """The workspace's rules, oldest first, each with the last thing it did."""
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(JiraTrigger)
                .where(JiraTrigger.workspace_id == workspace_id)
                .order_by(JiraTrigger.created_at, JiraTrigger.id)
            )
        ).all()
        last = await _last_fires(session, [row.id for row in rows])
    return [_info(row, last.get(row.id)) for row in rows]


async def get_jira_trigger(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, trigger_id: UUID
) -> JiraTriggerInfo | None:
    async with sessions() as session:
        row = await _trigger(session, workspace_id, trigger_id)
        if row is None:
            return None
        last = await _last_fires(session, [row.id])
    return _info(row, last.get(row.id))


async def create_jira_trigger(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, fields: JiraTriggerFields
) -> JiraTriggerInfo:
    async with sessions.begin() as session:
        row = JiraTrigger(id=uuid4(), workspace_id=workspace_id)
        _assign(row, fields)
        session.add(row)
        await session.flush()
        audit(session, workspace_id, "jira.trigger_created", details=_audit_details(row))
        await session.refresh(row)
    return _info(row, None)


async def update_jira_trigger(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    trigger_id: UUID,
    fields: JiraTriggerFields,
) -> JiraTriggerInfo:
    """Replaces what the rule says. `JiraTriggerNotFoundError` for an unknown rule."""
    async with sessions.begin() as session:
        row = await _trigger(session, workspace_id, trigger_id, lock=True)
        if row is None:
            raise JiraTriggerNotFoundError(str(trigger_id))
        _assign(row, fields)
        row.updated_at = datetime.now(UTC)
        audit(session, workspace_id, "jira.trigger_updated", details=_audit_details(row))
        await session.flush()
        last = await _last_fires(session, [row.id])
    return _info(row, last.get(row.id))


async def delete_jira_trigger(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, trigger_id: UUID
) -> None:
    """Deletes the rule and what it fired (its runs keep the issue, and lose the rule).
    `JiraTriggerNotFoundError` for an unknown rule."""
    async with sessions.begin() as session:
        row = await _trigger(session, workspace_id, trigger_id, lock=True)
        if row is None:
            raise JiraTriggerNotFoundError(str(trigger_id))
        audit(session, workspace_id, "jira.trigger_deleted", details=_audit_details(row))
        await session.delete(row)


async def matching_jira_triggers(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    cloud_id: str,
    project_key: str,
    *,
    status_to: str | None,
    labels_added: Sequence[str],
) -> list[JiraTriggerInfo]:
    """The workspace's enabled rules on the project that the event matches, oldest first."""
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(JiraTrigger)
                .where(
                    JiraTrigger.workspace_id == workspace_id,
                    JiraTrigger.cloud_id == cloud_id,
                    func.upper(JiraTrigger.project_key) == project_key.upper(),
                    JiraTrigger.enabled.is_(True),
                )
                .order_by(JiraTrigger.created_at, JiraTrigger.id)
            )
        ).all()
    return [
        _info(row, None)
        for row in rows
        if trigger_matches(row.on, row.value, status_to=status_to, labels_added=labels_added)
    ]


async def jira_trigger_projects(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> dict[str, list[str]]:
    """The projects the workspace's enabled rules use, by site: what its webhooks must cover."""
    async with sessions() as session:
        rows = (
            await session.execute(
                select(JiraTrigger.cloud_id, func.upper(JiraTrigger.project_key))
                .where(JiraTrigger.workspace_id == workspace_id, JiraTrigger.enabled.is_(True))
                .distinct()
            )
        ).all()
    projects: dict[str, list[str]] = {}
    for cloud_id, key in rows:
        projects.setdefault(cloud_id, []).append(key)
    return {cloud_id: sorted(keys) for cloud_id, keys in projects.items()}


# --- deliveries ------------------------------------------------------------------------------


async def record_jira_delivery(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    cloud_id: str,
    delivery_id: str,
    issue_key: str,
) -> int | None:
    """Records a delivery for the workspace; its row id, or `None` when it was already
    recorded (a retry, or a delivery sent twice)."""
    async with sessions.begin() as session:
        return await session.scalar(
            insert(JiraDelivery)
            .values(
                workspace_id=workspace_id,
                cloud_id=cloud_id,
                delivery_id=delivery_id[:64],
                issue_key=issue_key[:64],
            )
            .on_conflict_do_nothing(constraint="uq_jira_deliveries_delivery")
            .returning(JiraDelivery.id)
        )


async def set_jira_delivery_outcome(
    sessions: async_sessionmaker[AsyncSession], delivery_row: int, outcome: DeliveryOutcome
) -> None:
    async with sessions.begin() as session:
        row = await session.get(JiraDelivery, delivery_row)
        if row is not None:
            row.outcome = outcome


async def record_jira_trigger_fire(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    origin: JiraOrigin,
    outcome: Literal["already_running", "start_failed"],
    *,
    run_id: UUID | None = None,
    reason: str | None = None,
) -> None:
    """Records that a matching rule did not start a run: one was still going on the issue
    (`run_id`), or the start was refused (`reason`, audited as `jira.trigger_failed`). A
    started run is recorded by `create_run`, in the run's own transaction."""
    async with sessions.begin() as session:
        session.add(
            JiraTriggerFire(
                trigger_id=origin.trigger_id,
                delivery_id=origin.delivery_row,
                issue_key=origin.issue_key,
                outcome=outcome,
                reason=reason,
                run_id=run_id,
            )
        )
        if outcome == "start_failed":
            audit(
                session,
                workspace_id,
                "jira.trigger_failed",
                actor_type="system",
                details={
                    "trigger_id": str(origin.trigger_id),
                    "issue_key": origin.issue_key,
                    "reason": reason,
                },
            )


def add_trigger_run(
    session: AsyncSession, workspace_id: UUID, run: Run, origin: JiraOrigin
) -> None:
    """Marks `run` (being added to `session`) as started by the rule, records the fire and the
    `jira.trigger_fired` audit entry, committed with the run."""
    run.trigger = "jira"
    run.jira_trigger_id = origin.trigger_id
    run.jira_issue = origin.issue
    session.add(
        JiraTriggerFire(
            trigger_id=origin.trigger_id,
            delivery_id=origin.delivery_row,
            issue_key=origin.issue_key,
            outcome="started",
            run_id=run.id,
        )
    )
    audit(
        session,
        workspace_id,
        "jira.trigger_fired",
        actor_type="system",
        run_id=run.id,
        details={
            "trigger_id": str(origin.trigger_id),
            "issue_key": origin.issue_key,
            "delivery_id": origin.delivery_id,
        },
    )


async def lock_trigger_issue(session: AsyncSession, origin: JiraOrigin) -> None:
    """Holds a transaction lock for the rule and issue, then raises `TriggerRunActiveError` if
    a run it started on the issue is still queued, running or waiting. Two deliveries for one
    issue so cannot both start a run."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"jira-trigger:{origin.trigger_id}:{origin.issue_key}"},
    )
    active = await session.scalar(_active_run(origin.trigger_id, origin.issue_key))
    if active is not None:
        raise TriggerRunActiveError(active)


async def prune_jira_deliveries(
    sessions: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> int:
    """Deletes deliveries older than `DELIVERY_RETENTION`, and own moves past their window;
    how many deliveries."""
    now = now or datetime.now(UTC)
    async with sessions.begin() as session:
        result = await session.execute(
            delete(JiraDelivery).where(JiraDelivery.received_at < now - DELIVERY_RETENTION)
        )
        await session.execute(delete(JiraOwnMove).where(JiraOwnMove.at < now - OWN_MOVE_WINDOW))
    return int(getattr(result, "rowcount", 0) or 0)


# --- own moves -------------------------------------------------------------------------------


async def record_jira_own_move(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    cloud_id: str,
    issue_key: str,
    status: str,
    run_id: UUID | None,
) -> None:
    """Records that a run's own `jira.transition` moved the issue to `status`."""
    async with sessions.begin() as session:
        session.add(
            JiraOwnMove(
                workspace_id=workspace_id,
                cloud_id=cloud_id,
                issue_key=issue_key.upper()[:64],
                status=status[:255],
                run_id=run_id,
            )
        )


async def is_jira_own_move(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    cloud_id: str,
    issue_key: str,
    status: str,
    now: datetime | None = None,
) -> bool:
    """Whether a run moved the issue to `status` itself within `OWN_MOVE_WINDOW`."""
    since = (now or datetime.now(UTC)) - OWN_MOVE_WINDOW
    async with sessions() as session:
        found = await session.scalar(
            select(JiraOwnMove.id)
            .where(
                JiraOwnMove.workspace_id == workspace_id,
                JiraOwnMove.cloud_id == cloud_id,
                JiraOwnMove.issue_key == issue_key.upper(),
                func.lower(JiraOwnMove.status) == status.strip().lower(),
                JiraOwnMove.at >= since,
            )
            .limit(1)
        )
    return found is not None


# --- webhooks --------------------------------------------------------------------------------


@dataclass(frozen=True)
class JiraWebhookInfo:
    """The webhook a workspace holds on a site for its triggers, and its last failure."""

    workspace_id: UUID
    cloud_id: str
    webhook_id: int | None
    url: str | None
    projects: tuple[str, ...]
    expires_at: datetime | None
    renewed_at: datetime | None
    error: str | None
    error_at: datetime | None


async def list_jira_webhooks(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> list[JiraWebhookInfo]:
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(JiraWebhook)
                .where(JiraWebhook.workspace_id == workspace_id)
                .order_by(JiraWebhook.cloud_id)
            )
        ).all()
    return [_webhook(row) for row in rows]


async def get_jira_webhook(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, cloud_id: str
) -> JiraWebhookInfo | None:
    async with sessions() as session:
        row = await _webhook_row(session, workspace_id, cloud_id)
    return None if row is None else _webhook(row)


async def jira_webhook_workspaces(
    sessions: async_sessionmaker[AsyncSession], cloud_id: str, webhook_ids: Sequence[int]
) -> list[UUID]:
    """The workspaces whose webhook on the site is among `webhook_ids` (a delivery's
    `matchedWebhookIds`): one delivery reaches each of them once."""
    if not webhook_ids:
        return []
    async with sessions() as session:
        rows = await session.scalars(
            select(JiraWebhook.workspace_id)
            .where(JiraWebhook.cloud_id == cloud_id, JiraWebhook.webhook_id.in_(webhook_ids))
            .distinct()
        )
        return list(rows)


async def save_jira_webhook(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    cloud_id: str,
    *,
    webhook_id: int,
    url: str,
    projects: Sequence[str],
    expires_at: datetime | None,
) -> None:
    """Records the webhook as registered or renewed, clearing any failure. A new registration
    (another id) is audited as `jira.webhook_registered`."""
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        row = await _webhook_row(session, workspace_id, cloud_id, lock=True)
        if row is None:
            row = JiraWebhook(id=uuid4(), workspace_id=workspace_id, cloud_id=cloud_id)
            session.add(row)
        registered = row.webhook_id != webhook_id
        row.webhook_id = webhook_id
        row.url = url
        row.projects = sorted(projects)
        row.expires_at = expires_at
        row.renewed_at = now
        row.error = None
        row.error_at = None
        row.updated_at = now
        if registered:
            listed: list[JsonValue] = list(row.projects)
            audit(
                session,
                workspace_id,
                "jira.webhook_registered",
                actor_type="system",
                details={"cloud_id": cloud_id, "webhook_id": webhook_id, "projects": listed},
            )


async def set_jira_webhook_error(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, cloud_id: str, error: str
) -> bool:
    """Records why the site's webhook could not be registered or renewed. Audited as
    `jira.webhook_failed` once per failure: `False` when the same error was already recorded."""
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        row = await _webhook_row(session, workspace_id, cloud_id, lock=True)
        if row is None:
            row = JiraWebhook(id=uuid4(), workspace_id=workspace_id, cloud_id=cloud_id)
            session.add(row)
        if row.error == error:
            return False
        row.error = error
        row.error_at = now
        row.updated_at = now
        audit(
            session,
            workspace_id,
            "jira.webhook_failed",
            actor_type="system",
            details={"cloud_id": cloud_id, "webhook_id": row.webhook_id, "error": error},
        )
        return True


async def delete_jira_webhook(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, cloud_id: str
) -> None:
    """Forgets the site's webhook (the caller deleted it on Jira, or could not). A registered
    one is audited as `jira.webhook_deleted`."""
    async with sessions.begin() as session:
        row = await _webhook_row(session, workspace_id, cloud_id, lock=True)
        if row is None:
            return
        if row.webhook_id is not None:
            audit(
                session,
                workspace_id,
                "jira.webhook_deleted",
                actor_type="system",
                details={"cloud_id": cloud_id, "webhook_id": row.webhook_id},
            )
        await session.delete(row)


async def lock_jira_webhook(
    session: AsyncSession, workspace_id: UUID, cloud_id: str, *, wait: bool = False
) -> bool:
    """Takes the transaction lock that serialises work on one workspace's webhook on a site
    (a rule change in the API, the workers' sweep). With `wait`, waits for it; else `False` if
    another holds it."""
    key = {"key": f"jira-webhook:{workspace_id}:{cloud_id}"}
    if wait:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), key)
        return True
    taken = await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"), key
    )
    return bool(taken)


async def jira_webhook_sites(sessions: async_sessionmaker[AsyncSession]) -> list[tuple[UUID, str]]:
    """Every workspace and site that has a webhook row or an enabled rule: what the sweep
    looks at."""
    async with sessions() as session:
        held = (await session.execute(select(JiraWebhook.workspace_id, JiraWebhook.cloud_id))).all()
        wanted = (
            await session.execute(
                select(JiraTrigger.workspace_id, JiraTrigger.cloud_id)
                .where(JiraTrigger.enabled.is_(True))
                .distinct()
            )
        ).all()
    return sorted({(w, c) for w, c in held} | {(w, c) for w, c in wanted})


def _webhook(row: JiraWebhook) -> JiraWebhookInfo:
    return JiraWebhookInfo(
        workspace_id=row.workspace_id,
        cloud_id=row.cloud_id,
        webhook_id=row.webhook_id,
        url=row.url,
        projects=tuple(row.projects or ()),
        expires_at=row.expires_at,
        renewed_at=row.renewed_at,
        error=row.error,
        error_at=row.error_at,
    )


async def _webhook_row(
    session: AsyncSession, workspace_id: UUID, cloud_id: str, *, lock: bool = False
) -> JiraWebhook | None:
    query = select(JiraWebhook).where(
        JiraWebhook.workspace_id == workspace_id, JiraWebhook.cloud_id == cloud_id
    )
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


# --- helpers ---------------------------------------------------------------------------------


def _active_run(trigger_id: UUID, issue_key: str) -> Select[UUID]:
    return (
        select(Run.id)
        .where(
            Run.jira_trigger_id == trigger_id,
            Run.status.in_(ACTIVE_STATUSES),
            Run.jira_issue["key"].astext == issue_key,
        )
        .limit(1)
    )


async def _trigger(
    session: AsyncSession, workspace_id: UUID, trigger_id: UUID, *, lock: bool = False
) -> JiraTrigger | None:
    query = select(JiraTrigger).where(
        JiraTrigger.workspace_id == workspace_id, JiraTrigger.id == trigger_id
    )
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


async def _last_fires(
    session: AsyncSession, trigger_ids: Sequence[UUID]
) -> dict[UUID, JiraTriggerFireInfo]:
    if not trigger_ids:
        return {}
    rows = (
        await session.scalars(
            select(JiraTriggerFire)
            .where(JiraTriggerFire.trigger_id.in_(trigger_ids))
            .ext(distinct_on(JiraTriggerFire.trigger_id))
            .order_by(
                JiraTriggerFire.trigger_id, JiraTriggerFire.at.desc(), JiraTriggerFire.id.desc()
            )
        )
    ).all()
    return {
        row.trigger_id: JiraTriggerFireInfo(
            at=row.at,
            outcome=row.outcome,
            issue_key=row.issue_key,
            run_id=row.run_id,
            reason=row.reason,
        )
        for row in rows
    }


def _assign(row: JiraTrigger, fields: JiraTriggerFields) -> None:
    row.cloud_id = fields.cloud_id
    row.project_key = fields.project_key.upper()
    row.on = fields.on
    row.value = fields.value.strip()
    row.template_id = fields.template_id
    row.workflow_id = fields.workflow_id
    row.workflow_version = fields.workflow_version
    row.repo_url = fields.repo_url
    row.ref = fields.ref
    row.enabled = fields.enabled


def _info(row: JiraTrigger, last: JiraTriggerFireInfo | None) -> JiraTriggerInfo:
    on: TriggerOn = "label" if row.on == "label" else "status"
    return JiraTriggerInfo(
        id=row.id,
        workspace_id=row.workspace_id,
        fields=JiraTriggerFields(
            cloud_id=row.cloud_id,
            project_key=row.project_key,
            on=on,
            value=row.value,
            template_id=row.template_id,
            workflow_id=row.workflow_id,
            workflow_version=row.workflow_version,
            repo_url=row.repo_url,
            ref=row.ref,
            enabled=row.enabled,
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last=last,
    )


def _audit_details(row: JiraTrigger) -> dict[str, JsonValue]:
    return {
        "trigger_id": str(row.id),
        "cloud_id": row.cloud_id,
        "project_key": row.project_key,
        "on": row.on,
        "value": row.value,
        "enabled": row.enabled,
        **({"template_id": row.template_id} if row.template_id else {}),
        **({"workflow_id": row.workflow_id} if row.workflow_id else {}),
    }
