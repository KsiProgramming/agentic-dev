"""A workspace's Jira connection (7.1): an Atlassian OAuth grant, the sites it reaches and the
projects the workspace may use on each.

The grant (its access and refresh tokens) is one secret, encrypted under the workspace's data
key like every other connection's; this module never looks inside it. Sites, projects and the
granted scopes are not secrets and are stored in the clear. Atlassian's consent is per site, so
the picked projects are the platform's own allowlist: `jira_project_allowed` is the one check.

Refresh tokens rotate, so two refreshes must not race: `refresh_jira_secret` holds a row lock
on the connection while the caller's `refresh` runs, and stores what it returns before the lock
is released."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_secrets import KeyProvider, SecretDecryptError, WrappedKey, decrypt, encrypt
from agentic_store.audit import audit
from agentic_store.connections import (
    WorkspaceNotFoundError,
    dek_context,
    secret_aad,
    workspace_dek,
)
from agentic_store.models import Connection, JiraProject, JiraSite, Workspace

JIRA = "jira"

# How many project keys an audit entry lists; the count is always exact.
_AUDIT_KEYS = 50


class JiraNotConnectedError(LookupError):
    """The workspace has no Jira connection."""


class JiraNeedsAttentionError(RuntimeError):
    """The workspace's Jira connection cannot be used until its account connects again;
    `reason` says why (`invalid_grant`, `scopes`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the Jira connection needs attention: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class JiraSiteRef:
    """A site as Atlassian names it."""

    cloud_id: str
    url: str
    name: str


@dataclass(frozen=True)
class JiraProjectRef:
    project_id: str
    key: str
    name: str


@dataclass(frozen=True)
class JiraSiteInfo:
    cloud_id: str
    url: str
    name: str
    enabled: bool
    projects: tuple[JiraProjectRef, ...]


@dataclass(frozen=True)
class JiraConnectionInfo:
    """A workspace's Jira connection, without its tokens."""

    id: UUID
    workspace_id: UUID
    account: str | None
    scopes: tuple[str, ...]
    needs_attention: str | None
    sites: tuple[JiraSiteInfo, ...]
    created_at: datetime
    updated_at: datetime


async def put_jira_connection(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    workspace_id: UUID,
    secret: SecretStr,
    *,
    account: str,
    scopes: Sequence[str],
    sites: Sequence[JiraSiteRef],
    needs_attention: str | None = None,
) -> JiraConnectionInfo:
    """Store a grant as the workspace's Jira connection, replacing any earlier one.

    A site the earlier grant reached and this one still does keeps its `enabled` choice and its
    picked projects; a site no longer reached is dropped with its projects."""
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        workspace = await session.get(Workspace, workspace_id, with_for_update=True)
        if workspace is None:
            raise WorkspaceNotFoundError(workspace_id)
        dek = await workspace_dek(session, keys, workspace, now)
        connection = await _connection(session, workspace_id)
        replaced = connection is not None
        if connection is None:
            connection = Connection(
                id=uuid4(), workspace_id=workspace_id, provider=JIRA, created_at=now
            )
            session.add(connection)
        nonce, ciphertext = encrypt(dek, secret, secret_aad(connection))
        connection.secret_nonce = nonce
        connection.secret_ciphertext = ciphertext
        connection.account_login = account
        connection.scopes = list(scopes)
        connection.needs_attention = needs_attention
        connection.updated_at = now
        await session.flush()

        existing = {
            site.cloud_id: site
            for site in await session.scalars(
                select(JiraSite).where(JiraSite.connection_id == connection.id)
            )
        }
        reached = {site.cloud_id for site in sites}
        for cloud_id, site in existing.items():
            if cloud_id not in reached:
                await session.delete(site)
        for ref in sites:
            site = existing.get(ref.cloud_id)
            if site is None:
                session.add(
                    JiraSite(
                        id=uuid4(),
                        connection_id=connection.id,
                        cloud_id=ref.cloud_id,
                        url=ref.url,
                        name=ref.name,
                    )
                )
            else:
                site.url = ref.url
                site.name = ref.name
        audit(
            session,
            workspace_id,
            "connection.added",
            details={
                "provider": JIRA,
                "account_login": account,
                "sites": len(sites),
                "replaced": replaced,
            },
        )
        await session.flush()
        return await _info(session, connection)


async def get_jira_connection(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> JiraConnectionInfo | None:
    """The workspace's Jira connection with its sites and picked projects, or `None`."""
    async with sessions() as session:
        if await session.get(Workspace, workspace_id) is None:
            raise WorkspaceNotFoundError(workspace_id)
        connection = await _connection(session, workspace_id)
        return None if connection is None else await _info(session, connection)


async def set_jira_site_enabled(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, cloud_id: str, enabled: bool
) -> JiraSiteInfo | None:
    """Turn a site on or off for the workspace; its picked projects are kept. `None` if the
    workspace's connection has no such site."""
    async with sessions.begin() as session:
        site = await _site(session, workspace_id, cloud_id, lock=True)
        if site is None:
            return None
        if site.enabled != enabled:
            site.enabled = enabled
            audit(
                session,
                workspace_id,
                "jira.site_updated",
                details={"site": site.name, "cloud_id": cloud_id, "enabled": enabled},
            )
        return await _site_info(session, site)


async def set_jira_site_projects(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    cloud_id: str,
    projects: Sequence[JiraProjectRef],
) -> JiraSiteInfo | None:
    """Replace the projects the workspace may use on a site. `None` if the workspace's
    connection has no such site."""
    async with sessions.begin() as session:
        site = await _site(session, workspace_id, cloud_id, lock=True)
        if site is None:
            return None
        await session.execute(delete(JiraProject).where(JiraProject.site_id == site.id))
        unique = {p.project_id: p for p in projects}
        for project in unique.values():
            session.add(
                JiraProject(
                    id=uuid4(),
                    site_id=site.id,
                    project_id=project.project_id,
                    key=project.key,
                    name=project.name,
                )
            )
        keys = sorted(p.key for p in unique.values())
        audit(
            session,
            workspace_id,
            "jira.projects_changed",
            details={
                "site": site.name,
                "cloud_id": cloud_id,
                "count": len(keys),
                "keys": list(keys[:_AUDIT_KEYS]),
            },
        )
        await session.flush()
        return await _site_info(session, site)


async def jira_project_allowed(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, cloud_id: str, key: str
) -> bool:
    """Whether the workspace may use the project `key` of the site: it was picked, its site is
    on and the connection does not need attention. Keys compare without case, as Jira's do."""
    async with sessions() as session:
        found = await session.scalar(
            select(JiraProject.id)
            .join(JiraSite, JiraSite.id == JiraProject.site_id)
            .join(Connection, Connection.id == JiraSite.connection_id)
            .where(
                Connection.workspace_id == workspace_id,
                Connection.provider == JIRA,
                Connection.needs_attention.is_(None),
                JiraSite.cloud_id == cloud_id,
                JiraSite.enabled.is_(True),
                JiraProject.key == key.upper(),
            )
            .limit(1)
        )
        return found is not None


async def mark_jira_needs_attention(
    sessions: async_sessionmaker[AsyncSession], workspace_id: UUID, reason: str
) -> bool:
    """Record that the connection cannot be used until its account connects again. `False` if
    there is no connection or it was already marked (the audit entry is written once)."""
    async with sessions.begin() as session:
        connection = await _connection(session, workspace_id, lock=True)
        if connection is None or connection.needs_attention is not None:
            return False
        connection.needs_attention = reason
        connection.updated_at = datetime.now(UTC)
        audit(
            session,
            workspace_id,
            "connection.needs_attention",
            actor_type="system",
            details={"provider": JIRA, "reason": reason},
        )
        return True


async def refresh_jira_secret(
    sessions: async_sessionmaker[AsyncSession],
    keys: KeyProvider,
    workspace_id: UUID,
    refresh: Callable[[SecretStr], Awaitable[SecretStr | None]],
) -> SecretStr:
    """The connection's secret, after `refresh` had its chance to replace it.

    `refresh` gets the stored secret while the connection's row is locked, and returns a new
    one to store or `None` to keep it. If it raises, nothing is stored and the lock is released.
    Raises `JiraNotConnectedError`, `JiraNeedsAttentionError` or `SecretDecryptError`."""
    async with sessions.begin() as session:
        connection = await _connection(session, workspace_id, lock=True)
        if (
            connection is None
            or connection.secret_nonce is None
            or connection.secret_ciphertext is None
        ):
            raise JiraNotConnectedError(workspace_id)
        if connection.needs_attention is not None:
            raise JiraNeedsAttentionError(connection.needs_attention)
        workspace = await session.get_one(Workspace, workspace_id)
        if workspace.wrapped_dek is None or workspace.key_id is None:
            raise SecretDecryptError("the workspace has no data key")
        dek = keys.unwrap(
            WrappedKey(workspace.key_id, workspace.wrapped_dek), dek_context(workspace)
        )
        aad = secret_aad(connection)
        current = decrypt(dek, connection.secret_nonce, connection.secret_ciphertext, aad)
        replacement = await refresh(current)
        if replacement is None:
            return current
        connection.secret_nonce, connection.secret_ciphertext = encrypt(dek, replacement, aad)
        connection.updated_at = datetime.now(UTC)
        return replacement


async def _connection(
    session: AsyncSession, workspace_id: UUID, *, lock: bool = False
) -> Connection | None:
    query = select(Connection).where(
        Connection.workspace_id == workspace_id, Connection.provider == JIRA
    )
    return await session.scalar(query.with_for_update() if lock else query)


async def _site(
    session: AsyncSession, workspace_id: UUID, cloud_id: str, *, lock: bool = False
) -> JiraSite | None:
    query = (
        select(JiraSite)
        .join(Connection, Connection.id == JiraSite.connection_id)
        .where(
            Connection.workspace_id == workspace_id,
            Connection.provider == JIRA,
            JiraSite.cloud_id == cloud_id,
        )
    )
    return await session.scalar(query.with_for_update(of=JiraSite) if lock else query)


async def _site_info(session: AsyncSession, site: JiraSite) -> JiraSiteInfo:
    projects = await session.scalars(
        select(JiraProject).where(JiraProject.site_id == site.id).order_by(JiraProject.key)
    )
    return JiraSiteInfo(
        cloud_id=site.cloud_id,
        url=site.url,
        name=site.name,
        enabled=site.enabled,
        projects=tuple(
            JiraProjectRef(project_id=p.project_id, key=p.key, name=p.name) for p in projects
        ),
    )


async def _info(session: AsyncSession, connection: Connection) -> JiraConnectionInfo:
    sites = await session.scalars(
        select(JiraSite).where(JiraSite.connection_id == connection.id).order_by(JiraSite.name)
    )
    return JiraConnectionInfo(
        id=connection.id,
        workspace_id=connection.workspace_id,
        account=connection.account_login,
        scopes=tuple(connection.scopes or ()),
        needs_attention=connection.needs_attention,
        sites=tuple([await _site_info(session, site) for site in sites]),
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )
