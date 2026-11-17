import os
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_secrets import KEY_BYTES, LocalKeyProvider, SecretDecryptError
from agentic_store import (
    JIRA,
    AuditEvent,
    Connection,
    JiraFieldMapping,
    JiraMappedField,
    JiraNeedsAttentionError,
    JiraNotConnectedError,
    JiraProject,
    JiraProjectRef,
    JiraSite,
    JiraSiteRef,
    Workspace,
    delete_connection,
    get_jira_connection,
    jira_project_allowed,
    jira_site_field_mappings,
    list_connections,
    mark_jira_needs_attention,
    put_jira_connection,
    refresh_jira_secret,
    set_jira_project_fields,
    set_jira_site_enabled,
    set_jira_site_projects,
)

pytestmark = pytest.mark.integration

KEYS = LocalKeyProvider(os.urandom(KEY_BYTES))
GRANT = SecretStr('{"access_token":"at-store-0001","refresh_token":"rt-store-0001"}')
ACME = JiraSiteRef("cloud-acme", "https://acme.atlassian.net", "Acme")
LABS = JiraSiteRef("cloud-labs", "https://labs.atlassian.net", "Labs")
WEB = JiraProjectRef("10001", "WEB", "Web shop")
API = JiraProjectRef("10002", "API", "Public API")
SCOPES = ("read:jira-work", "offline_access")

Sessions = async_sessionmaker[AsyncSession]


async def new_workspace(sessions: Sessions) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def connected(sessions: Sessions, *sites: JiraSiteRef) -> UUID:
    workspace_id = await new_workspace(sessions)
    await put_jira_connection(
        sessions, KEYS, workspace_id, GRANT, account="Ada", scopes=SCOPES, sites=sites or (ACME,)
    )
    return workspace_id


async def audit_actions(sessions: Sessions, workspace_id: UUID) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.id)
        )
        return list(rows)


async def keep(secret: SecretStr) -> SecretStr | None:
    return None


async def test_a_grant_is_stored_encrypted_with_its_sites(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)

    info = await put_jira_connection(
        sessions, KEYS, workspace_id, GRANT, account="Ada", scopes=SCOPES, sites=(LABS, ACME)
    )

    assert info.account == "Ada"
    assert info.scopes == SCOPES
    assert info.needs_attention is None
    assert [(s.name, s.enabled, s.projects) for s in info.sites] == [
        ("Acme", True, ()),
        ("Labs", True, ()),
    ]
    assert await get_jira_connection(sessions, workspace_id) == info
    assert await refresh_jira_secret(sessions, KEYS, workspace_id, keep) == GRANT
    async with sessions() as session:
        row = await session.scalar(
            select(Connection).where(Connection.workspace_id == workspace_id)
        )
    assert row is not None and row.secret_ciphertext is not None
    assert row.key_hint is None
    for token in (b"at-store-0001", b"rt-store-0001"):
        assert token not in row.secret_ciphertext
    assert "at-store-0001" not in repr(info)
    [listed] = await list_connections(sessions, workspace_id)
    assert (listed.provider, listed.account_login, listed.key_hint) == (JIRA, "Ada", None)


async def test_another_master_key_cannot_read_the_grant(sessions: Sessions) -> None:
    workspace_id = await connected(sessions)

    with pytest.raises(SecretDecryptError):
        await refresh_jira_secret(
            sessions, LocalKeyProvider(os.urandom(KEY_BYTES)), workspace_id, keep
        )


async def test_a_reconnect_keeps_the_projects_of_sites_still_reached(sessions: Sessions) -> None:
    workspace_id = await connected(sessions, ACME, LABS)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB, API])
    await set_jira_site_projects(sessions, workspace_id, LABS.cloud_id, [WEB])
    await set_jira_site_enabled(sessions, workspace_id, ACME.cloud_id, False)
    await mark_jira_needs_attention(sessions, workspace_id, "invalid_grant")
    renamed = JiraSiteRef(ACME.cloud_id, ACME.url, "Acme Corp")
    again = SecretStr('{"access_token":"at-store-0002"}')

    info = await put_jira_connection(
        sessions, KEYS, workspace_id, again, account="Ada", scopes=SCOPES, sites=(renamed,)
    )

    [site] = info.sites
    assert (site.name, site.enabled, site.projects) == ("Acme Corp", False, (API, WEB))
    assert info.needs_attention is None
    assert await refresh_jira_secret(sessions, KEYS, workspace_id, keep) == again
    async with sessions() as session:
        sites = await session.scalar(
            select(func.count()).select_from(JiraSite).where(JiraSite.connection_id == info.id)
        )
    assert sites == 1


async def test_only_picked_projects_of_an_enabled_site_are_allowed(sessions: Sessions) -> None:
    workspace_id = await connected(sessions, ACME, LABS)
    other = await connected(sessions, ACME)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB, WEB])

    assert await jira_project_allowed(sessions, workspace_id, ACME.cloud_id, "WEB")
    assert await jira_project_allowed(sessions, workspace_id, ACME.cloud_id, "web")
    assert not await jira_project_allowed(sessions, workspace_id, ACME.cloud_id, "API")
    assert not await jira_project_allowed(sessions, workspace_id, LABS.cloud_id, "WEB")
    assert not await jira_project_allowed(sessions, other, ACME.cloud_id, "WEB")

    await set_jira_site_enabled(sessions, workspace_id, ACME.cloud_id, False)
    assert not await jira_project_allowed(sessions, workspace_id, ACME.cloud_id, "WEB")
    site = await set_jira_site_enabled(sessions, workspace_id, ACME.cloud_id, True)
    assert site is not None and site.projects == (WEB,)
    assert await jira_project_allowed(sessions, workspace_id, ACME.cloud_id, "WEB")

    await mark_jira_needs_attention(sessions, workspace_id, "invalid_grant")
    assert not await jira_project_allowed(sessions, workspace_id, ACME.cloud_id, "WEB")


async def test_an_unknown_site_changes_nothing(sessions: Sessions) -> None:
    workspace_id = await connected(sessions)

    assert await set_jira_site_projects(sessions, workspace_id, "cloud-nope", [WEB]) is None
    assert await set_jira_site_enabled(sessions, workspace_id, "cloud-nope", False) is None


async def test_refresh_stores_what_it_returns_and_nothing_when_it_raises(
    sessions: Sessions,
) -> None:
    workspace_id = await connected(sessions)
    rotated = SecretStr('{"access_token":"at-store-0003"}')
    seen: list[SecretStr] = []

    async def rotate(current: SecretStr) -> SecretStr | None:
        seen.append(current)
        return rotated

    async def fail(current: SecretStr) -> SecretStr | None:
        raise RuntimeError("refused")

    assert await refresh_jira_secret(sessions, KEYS, workspace_id, rotate) == rotated
    assert seen == [GRANT]
    with pytest.raises(RuntimeError):
        await refresh_jira_secret(sessions, KEYS, workspace_id, fail)
    assert await refresh_jira_secret(sessions, KEYS, workspace_id, keep) == rotated


async def test_a_connection_that_needs_attention_gives_no_secret(sessions: Sessions) -> None:
    workspace_id = await connected(sessions)

    assert await mark_jira_needs_attention(sessions, workspace_id, "invalid_grant")
    assert not await mark_jira_needs_attention(sessions, workspace_id, "invalid_grant")

    with pytest.raises(JiraNeedsAttentionError) as refused:
        await refresh_jira_secret(sessions, KEYS, workspace_id, keep)
    assert refused.value.reason == "invalid_grant"
    info = await get_jira_connection(sessions, workspace_id)
    assert info is not None and info.needs_attention == "invalid_grant"
    assert (await audit_actions(sessions, workspace_id)).count("connection.needs_attention") == 1


async def test_deleting_the_connection_deletes_its_sites_and_projects(
    sessions: Sessions,
) -> None:
    workspace_id = await connected(sessions)
    info = await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB])
    assert info is not None

    assert await delete_connection(sessions, workspace_id, JIRA)

    assert await get_jira_connection(sessions, workspace_id) is None
    with pytest.raises(JiraNotConnectedError):
        await refresh_jira_secret(sessions, KEYS, workspace_id, keep)
    async with sessions() as session:
        left = await session.scalar(
            select(func.count())
            .select_from(JiraProject)
            .join(JiraSite, JiraSite.id == JiraProject.site_id)
            .where(JiraSite.cloud_id == ACME.cloud_id, JiraProject.project_id == WEB.project_id)
            .join(Connection, Connection.id == JiraSite.connection_id)
            .where(Connection.workspace_id == workspace_id)
        )
    assert left == 0
    assert await audit_actions(sessions, workspace_id) == [
        "connection.added",
        "jira.projects_changed",
        "connection.removed",
    ]


AC = JiraMappedField("acceptance_criteria", "customfield_10100", "Acceptance criteria")
POINTS = JiraMappedField("story_points", "customfield_10016", "Story point estimate")


async def test_a_project_maps_its_fields_and_lists_them(sessions: Sessions) -> None:
    workspace_id = await connected(sessions)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB, API])

    saved = await set_jira_project_fields(
        sessions, workspace_id, ACME.cloud_id, "web", [POINTS, AC]
    )

    assert saved is not None and saved.fields == (AC, POINTS)
    info = await get_jira_connection(sessions, workspace_id)
    assert info is not None
    by_key = {p.key: p for p in info.sites[0].projects}
    assert by_key["WEB"].fields == (AC, POINTS)
    assert by_key["API"].fields == ()
    assert await jira_site_field_mappings(sessions, workspace_id, ACME.cloud_id) == {
        "WEB": {"acceptance_criteria": "customfield_10100", "story_points": "customfield_10016"}
    }
    assert (await audit_actions(sessions, workspace_id))[-1] == "jira.fields_mapped"


async def test_a_mapping_is_replaced_whole(sessions: Sessions) -> None:
    workspace_id = await connected(sessions)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB])
    await set_jira_project_fields(sessions, workspace_id, ACME.cloud_id, "WEB", [AC, POINTS])

    saved = await set_jira_project_fields(sessions, workspace_id, ACME.cloud_id, "WEB", [POINTS])

    assert saved is not None and saved.fields == (POINTS,)
    assert await jira_site_field_mappings(sessions, workspace_id, ACME.cloud_id) == {
        "WEB": {"story_points": "customfield_10016"}
    }


async def test_only_a_picked_project_maps_fields(sessions: Sessions) -> None:
    workspace_id = await connected(sessions, ACME, LABS)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB])

    assert await set_jira_project_fields(sessions, workspace_id, ACME.cloud_id, "API", [AC]) is None
    assert await set_jira_project_fields(sessions, workspace_id, LABS.cloud_id, "WEB", [AC]) is None
    assert await set_jira_project_fields(sessions, workspace_id, "cloud-x", "WEB", [AC]) is None
    other = await connected(sessions)
    assert await jira_site_field_mappings(sessions, other, ACME.cloud_id) == {}


async def test_saving_projects_keeps_the_mappings_of_those_still_picked(sessions: Sessions) -> None:
    workspace_id = await connected(sessions)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB, API])
    await set_jira_project_fields(sessions, workspace_id, ACME.cloud_id, "WEB", [AC])
    await set_jira_project_fields(sessions, workspace_id, ACME.cloud_id, "API", [POINTS])
    renamed = JiraProjectRef(WEB.project_id, "SHOP", "Shop")

    info = await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [renamed])

    assert info is not None
    assert info.projects == (JiraProjectRef(WEB.project_id, "SHOP", "Shop", (AC,)),)
    assert await jira_site_field_mappings(sessions, workspace_id, ACME.cloud_id) == {
        "SHOP": {"acceptance_criteria": "customfield_10100"}
    }
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [API])
    assert await jira_site_field_mappings(sessions, workspace_id, ACME.cloud_id) == {}


async def test_mappings_go_with_the_connection_and_with_a_site_no_longer_reached(
    sessions: Sessions,
) -> None:
    workspace_id = await connected(sessions, ACME, LABS)
    await set_jira_site_projects(sessions, workspace_id, ACME.cloud_id, [WEB])
    await set_jira_site_projects(sessions, workspace_id, LABS.cloud_id, [WEB])
    await set_jira_project_fields(sessions, workspace_id, ACME.cloud_id, "WEB", [AC])
    await set_jira_project_fields(sessions, workspace_id, LABS.cloud_id, "WEB", [AC])

    await put_jira_connection(
        sessions, KEYS, workspace_id, GRANT, account="Ada", scopes=SCOPES, sites=(ACME,)
    )
    assert await jira_site_field_mappings(sessions, workspace_id, ACME.cloud_id) == {
        "WEB": {"acceptance_criteria": "customfield_10100"}
    }
    assert await jira_site_field_mappings(sessions, workspace_id, LABS.cloud_id) == {}
    async with sessions() as session:
        ids = list(
            await session.scalars(
                select(JiraFieldMapping.id)
                .join(JiraProject, JiraProject.id == JiraFieldMapping.project_id)
                .join(JiraSite, JiraSite.id == JiraProject.site_id)
                .join(Connection, Connection.id == JiraSite.connection_id)
                .where(Connection.workspace_id == workspace_id)
            )
        )
    assert len(ids) == 1

    assert await delete_connection(sessions, workspace_id, JIRA)

    async with sessions() as session:
        left = await session.scalar(
            select(func.count()).select_from(JiraFieldMapping).where(JiraFieldMapping.id.in_(ids))
        )
    assert left == 0
