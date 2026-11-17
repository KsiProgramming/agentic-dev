"""Keeping a workspace's trigger webhooks on Jira in step with its rules (7.3).

For each site, the webhook must cover the projects its enabled rules use, among those the
workspace picked on an enabled site; with none, it must not exist. `sync_jira_webhooks` makes
it so: it lists the account's webhooks on the site (a refresh cannot tell that one is gone),
registers or registers again when the projects or the URL changed (deleting the old one first,
since Jira allows one URL per account), renews one that expires within `RENEW_WITHIN`, and
deletes one no rule needs. The API runs it after a change to rules, sites, projects or the
connection; every worker runs it on a timer to renew (`url=None`: the URL stored on the row).

Work on one site of one workspace is serialised by a transaction lock, so a rule change and a
sweep never register twice. A failure is stored on the row and audited once; it never raises."""

import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_jira.errors import JiraApiError, JiraWebhookError
from agentic_jira.models import Webhook
from agentic_jira.platform import JiraPlatform
from agentic_jira.tokens import call
from agentic_secrets import KeyProvider, SecretDecryptError
from agentic_store import (
    JiraConnectionInfo,
    JiraNeedsAttentionError,
    JiraNotConnectedError,
    delete_jira_webhook,
    get_jira_connection,
    get_jira_webhook,
    jira_trigger_projects,
    jira_webhook_sites,
    list_jira_webhooks,
    lock_jira_webhook,
    save_jira_webhook,
    set_jira_webhook_error,
)

WEBHOOK_PATH = "/jira/webhooks"
RENEW_WITHIN = timedelta(days=10)
WEBHOOK_LIFE = timedelta(days=30)

SiteState = Literal["listening", "not_needed", "failed", "busy"]


@dataclass(frozen=True)
class SiteSync:
    cloud_id: str
    state: SiteState
    error: str | None = None


def webhook_url(base_url: str) -> str:
    """Where Jira posts deliveries: one URL for every workspace (Jira allows one per account)."""
    return f"{base_url.rstrip('/')}{WEBHOOK_PATH}"


async def sync_jira_webhooks(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    platform: JiraPlatform,
    workspace_id: UUID,
    url: str | None,
    *,
    renew_within: timedelta = RENEW_WITHIN,
    wait: bool = True,
) -> list[SiteSync]:
    """Brings the workspace's webhooks in step with its rules, site by site. `url` is where
    Jira must post; `None` keeps each row's (the sweep's renewals). With `wait` (a change in
    the API) it waits for a sweep working on the same site; without (the sweep) it skips the
    site (`busy`), which the other's work covers."""
    connection = await get_jira_connection(sessions, workspace_id)
    wanted = _wanted(connection, await jira_trigger_projects(sessions, workspace_id))
    held = {row.cloud_id for row in await list_jira_webhooks(sessions, workspace_id)}
    reachable = {site.cloud_id for site in connection.sites} if connection else set[str]()
    results: list[SiteSync] = []
    for cloud_id in sorted(set(wanted) | held):
        site = _Site(sessions, keys, platform, workspace_id, cloud_id)
        async with sessions.begin() as session:
            if not await lock_jira_webhook(session, workspace_id, cloud_id, wait=wait):
                results.append(SiteSync(cloud_id, "busy"))
                continue
            results.append(
                await site.sync(
                    wanted.get(cloud_id, []), url, renew_within, reachable=cloud_id in reachable
                )
            )
    return results


async def renew_jira_webhooks(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    platform: JiraPlatform,
    *,
    renew_within: timedelta = RENEW_WITHIN,
) -> list[tuple[UUID, SiteSync]]:
    """The workers' sweep: every workspace with a webhook or an enabled rule is synced with the
    URL stored on its rows, so a webhook near its expiry is renewed and one gone from Jira is
    registered again. One workspace's failure does not stop the others."""
    results: list[tuple[UUID, SiteSync]] = []
    for workspace_id in sorted({w for w, _ in await jira_webhook_sites(sessions)}):
        synced = await sync_jira_webhooks(
            sessions, keys, platform, workspace_id, None, renew_within=renew_within, wait=False
        )
        results.extend((workspace_id, site) for site in synced)
    return results


async def remove_jira_webhooks(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    platform: JiraPlatform,
    workspace_id: UUID,
) -> None:
    """Deletes the workspace's webhooks on Jira, as far as Jira lets us, and forgets them
    (before its Jira connection is removed)."""
    for row in await list_jira_webhooks(sessions, workspace_id):
        if row.webhook_id is not None:
            site = _Site(sessions, keys, platform, workspace_id, row.cloud_id)
            with contextlib.suppress(_Failed):  # the grant goes with the connection anyway
                await site.delete(row.webhook_id)
        await delete_jira_webhook(sessions, workspace_id, row.cloud_id)


def _wanted(
    connection: JiraConnectionInfo | None, projects: dict[str, list[str]]
) -> dict[str, list[str]]:
    """The projects each site's webhook must cover: the rules' projects that are picked on an
    enabled site of a connection that works."""
    if connection is None or connection.needs_attention is not None:
        return {}
    wanted: dict[str, list[str]] = {}
    for site in connection.sites:
        if not site.enabled:
            continue
        picked = {project.key.upper() for project in site.projects}
        keys = sorted(key for key in projects.get(site.cloud_id, []) if key in picked)
        if keys:
            wanted[site.cloud_id] = keys
    return wanted


class _Failed(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class _Site:
    """One workspace's webhook on one site, and the Jira calls about it."""

    sessions: async_sessionmaker[AsyncSession]
    keys: KeyProvider
    platform: JiraPlatform
    workspace_id: UUID
    cloud_id: str

    async def sync(
        self, projects: list[str], url: str | None, renew_within: timedelta, *, reachable: bool
    ) -> SiteSync:
        row = await get_jira_webhook(self.sessions, self.workspace_id, self.cloud_id)
        try:
            if not projects:
                if row is not None and row.webhook_id is not None and reachable:
                    await self.delete(row.webhook_id)
                if row is not None:
                    await delete_jira_webhook(self.sessions, self.workspace_id, self.cloud_id)
                return SiteSync(self.cloud_id, "not_needed")
            target = url or (row.url if row is not None else None)
            if target is None:
                raise _Failed("no_url")
            live = None
            if row is not None and row.webhook_id is not None:
                live = next((w for w in await self.list() if w.id == row.webhook_id), None)
            now = datetime.now(UTC)
            unchanged = row is not None and list(row.projects) == projects
            if live is not None and row is not None and live.url == target and unchanged:
                expires = row.expires_at or live.expires_at
                if expires is None or expires - now <= renew_within:
                    expires = await self.refresh(live.id) or now + WEBHOOK_LIFE
                await self.save(live.id, target, projects, expires)
                return SiteSync(self.cloud_id, "listening")
            if live is not None:
                await self.delete(live.id)
            webhook_id = await self._guarded(
                lambda token: self.platform.register_webhook(token, self.cloud_id, target, projects)
            )
            await self.save(webhook_id, target, projects, now + WEBHOOK_LIFE)
            return SiteSync(self.cloud_id, "listening")
        except _Failed as failed:
            await set_jira_webhook_error(
                self.sessions, self.workspace_id, self.cloud_id, failed.kind
            )
            return SiteSync(self.cloud_id, "failed", failed.kind)

    async def list(self) -> list[Webhook]:
        return await self._guarded(lambda token: self.platform.list_webhooks(token, self.cloud_id))

    async def refresh(self, webhook_id: int) -> datetime | None:
        return await self._guarded(
            lambda token: self.platform.refresh_webhooks(token, self.cloud_id, [webhook_id])
        )

    async def delete(self, webhook_id: int) -> None:
        await self._guarded(
            lambda token: self.platform.delete_webhooks(token, self.cloud_id, [webhook_id])
        )

    async def save(
        self, webhook_id: int, url: str, projects: Sequence[str], expires_at: datetime
    ) -> None:
        await save_jira_webhook(
            self.sessions,
            self.workspace_id,
            self.cloud_id,
            webhook_id=webhook_id,
            url=url,
            projects=projects,
            expires_at=expires_at,
        )

    async def _guarded[T](self, request: Callable[[SecretStr], Awaitable[T]]) -> T:
        """`request(token)`, its failures as one fixed kind."""
        try:
            return await call(self.sessions, self.keys, self.platform, self.workspace_id, request)
        except JiraWebhookError as exc:
            raise _Failed(exc.kind) from None
        except JiraNotConnectedError:
            raise _Failed("not_connected") from None
        except (JiraNeedsAttentionError, SecretDecryptError):
            raise _Failed("needs_attention") from None
        except JiraApiError:
            raise _Failed("jira_unavailable") from None
