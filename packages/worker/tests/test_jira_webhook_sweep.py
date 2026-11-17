"""The workers' sweep of Jira trigger webhooks (7.3): renewing before the 30-day expiry,
registering again what Jira dropped, and never twice at once."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_jira import FAKE_SITES, FakeAtlassian, renew_jira_webhooks, sync_jira_webhooks
from agentic_secrets import KEY_BYTES, LocalKeyProvider
from agentic_store import (
    JiraProjectRef,
    JiraSiteRef,
    JiraTriggerFields,
    JiraWebhook,
    Workspace,
    create_jira_trigger,
    get_jira_webhook,
    put_jira_connection,
    set_jira_site_projects,
)

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
KEYS = LocalKeyProvider(os.urandom(KEY_BYTES))
ACME = FAKE_SITES[0]
URL = "https://hooks.example.test/jira/webhooks"


async def workspace_with_rule(sessions: Sessions, atlassian: FakeAtlassian) -> UUID:
    """A workspace connected to the fake Jira, API picked on Acme, and one rule on it."""
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"sweep-{workspace_id.hex[:6]}"))
    grant = await atlassian.exchange("fake-code")
    await put_jira_connection(
        sessions,
        KEYS,
        workspace_id,
        grant.to_secret(),
        account="Ada",
        scopes=grant.scopes,
        sites=[JiraSiteRef(s.cloud_id, s.url, s.name) for s in FAKE_SITES],
    )
    await set_jira_site_projects(
        sessions, workspace_id, ACME.cloud_id, [JiraProjectRef("10001", "API", "Public API")]
    )
    await create_jira_trigger(
        sessions,
        workspace_id,
        JiraTriggerFields(
            cloud_id=ACME.cloud_id,
            project_key="API",
            on="status",
            value="In Progress",
            template_id="jira-issue-answer",
        ),
    )
    return workspace_id


async def test_the_sweep_renews_a_webhook_near_its_expiry(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("")
    workspace_id = await workspace_with_rule(sessions, atlassian)
    await sync_jira_webhooks(sessions, KEYS, atlassian, workspace_id, URL)
    row = await get_jira_webhook(sessions, workspace_id, ACME.cloud_id)
    assert row is not None and row.webhook_id is not None

    await renew_jira_webhooks(sessions, KEYS, atlassian)
    assert atlassian.refreshed == []  # 30 days left: nothing to do

    soon = datetime.now(UTC) + timedelta(days=3)
    async with sessions.begin() as session:
        await session.execute(
            update(JiraWebhook)
            .where(JiraWebhook.workspace_id == workspace_id)
            .values(expires_at=soon)
        )
    await renew_jira_webhooks(sessions, KEYS, atlassian)

    assert atlassian.refreshed == [(ACME.cloud_id, (row.webhook_id,))]
    renewed = await get_jira_webhook(sessions, workspace_id, ACME.cloud_id)
    assert renewed is not None and renewed.expires_at is not None
    assert renewed.expires_at > datetime.now(UTC) + timedelta(days=29)
    assert renewed.webhook_id == row.webhook_id  # renewed, not registered again


async def test_the_sweep_registers_again_a_webhook_jira_dropped(sessions: Sessions) -> None:
    atlassian = FakeAtlassian("")
    workspace_id = await workspace_with_rule(sessions, atlassian)
    await sync_jira_webhooks(sessions, KEYS, atlassian, workspace_id, URL)
    before = await get_jira_webhook(sessions, workspace_id, ACME.cloud_id)
    assert before is not None
    atlassian.webhooks[ACME.cloud_id].clear()  # expired past Jira's keeping, or deleted there

    await renew_jira_webhooks(sessions, KEYS, atlassian)

    after = await get_jira_webhook(sessions, workspace_id, ACME.cloud_id)
    assert after is not None and after.webhook_id is not None
    assert after.webhook_id != before.webhook_id
    hook = atlassian.webhooks[ACME.cloud_id][after.webhook_id]
    assert hook.url == URL  # with the URL it was stored with


async def test_two_syncs_at_once_register_one_webhook(sessions: Sessions) -> None:
    """The sweep on several workers, or a rule change during a sweep, on one workspace."""
    atlassian = FakeAtlassian("")
    workspace_id = await workspace_with_rule(sessions, atlassian)

    def sync(wait: bool):
        return sync_jira_webhooks(sessions, KEYS, atlassian, workspace_id, URL, wait=wait)

    swept = await asyncio.gather(sync(False), sync(False), sync(True), sync(True))

    assert len(atlassian.webhooks[ACME.cloud_id]) == 1
    # A sweep skips a site another holds; a change in the API waits its turn and is done.
    assert [site.state for site in swept[2] + swept[3]] == ["listening", "listening"]
    assert {site.state for synced in swept[:2] for site in synced} <= {"listening", "busy"}


async def test_a_sweep_failure_is_stored_and_the_next_success_clears_it(
    sessions: Sessions,
) -> None:
    atlassian = FakeAtlassian("")
    workspace_id = await workspace_with_rule(sessions, atlassian)
    await sync_jira_webhooks(sessions, KEYS, atlassian, workspace_id, URL)
    atlassian.unavailable = True
    async with sessions.begin() as session:
        await session.execute(
            update(JiraWebhook)
            .where(JiraWebhook.workspace_id == workspace_id)
            .values(expires_at=datetime.now(UTC))
        )

    results = await renew_jira_webhooks(sessions, KEYS, atlassian)
    mine = [site for w, site in results if w == workspace_id]
    assert [(s.state, s.error) for s in mine] == [("failed", "jira_unavailable")]

    atlassian.unavailable = False
    await renew_jira_webhooks(sessions, KEYS, atlassian)
    row = await get_jira_webhook(sessions, workspace_id, ACME.cloud_id)
    assert row is not None and row.error is None
