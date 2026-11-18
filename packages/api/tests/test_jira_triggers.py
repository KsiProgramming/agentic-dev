"""Jira triggers (7.3): rules, the webhook they keep on Jira, and deliveries starting runs."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_jira import FakeAtlassian, FakeDelivery, sign_delivery
from agentic_secrets import generate_key_file
from agentic_store import (
    AuditEvent,
    JiraDelivery,
    JiraTriggerFields,
    JiraWebhook,
    Run,
    create_jira_trigger,
    put_github_connection,
    record_jira_own_move,
    set_run_jira_brief,
)

pytestmark = pytest.mark.integration

ACME = "fake-cloud-acme"
REPO = {"url": "https://github.com/acme/app"}
STATUS_RULE: dict[str, Any] = {
    "cloud_id": ACME,
    "project_key": "API",
    "on": "status",
    "value": "In Progress",
    "template_id": "jira-issue-answer",
    "repo": REPO,
}
HOOK_URL = "https://hooks.example.test/jira/webhooks"

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def atlassian() -> FakeAtlassian:
    return FakeAtlassian("http://test")


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, tmp_path: Path, atlassian: FakeAtlassian, sessions: Sessions
) -> AsyncIterator[AsyncClient]:
    """`sessions` migrates the database first."""
    master_key = tmp_path / "master.key"
    generate_key_file(master_key)
    settings = Settings(
        database_url=postgres_url,
        redis_url=redis_url,
        master_key_file=master_key,
        web_base_url="http://web.test/",
        jira_webhook_base_url="https://hooks.example.test",
    )
    app = create_app(settings)
    app.state.jira = atlassian
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
async def workspace(client: AsyncClient) -> str:
    created = await client.post("/workspaces", json={"name": f"trig-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return f"/workspaces/{created.json()['id']}"


def workspace_id(workspace: str) -> UUID:
    return UUID(workspace.rsplit("/", 1)[1])


async def connected(client: AsyncClient, workspace: str, *project_ids: str) -> None:
    """Jira connected through the fake consent, with projects picked on Acme (API by default)."""
    started = await client.post(f"{workspace}/connections/jira/authorize")
    url = urlsplit(str(started.json()["authorize_url"]))
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (await client.get(url.path, params=params)).status_code == 303
    picked = await client.put(
        f"{workspace}/jira/sites/{ACME}/projects",
        json={"project_ids": list(project_ids or ("10001",))},
    )
    assert picked.status_code == 200, picked.text


async def rule(client: AsyncClient, workspace: str, **changes: Any) -> dict[str, Any]:
    created = await client.post(f"{workspace}/jira/triggers", json=STATUS_RULE | changes)
    assert created.status_code == 201, created.text
    return created.json()


async def deliver(client: AsyncClient, delivery: FakeDelivery) -> int:
    response = await client.post("/jira/webhooks", content=delivery.body, headers=delivery.headers)
    return response.status_code


async def runs_of(sessions: Sessions, workspace: str) -> list[Run]:
    async with sessions() as session:
        rows = await session.scalars(
            select(Run).where(Run.workspace_id == workspace_id(workspace)).order_by(Run.created_at)
        )
        return list(rows)


async def outcomes(sessions: Sessions, workspace: str) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(JiraDelivery.outcome)
            .where(JiraDelivery.workspace_id == workspace_id(workspace))
            .order_by(JiraDelivery.id)
        )
        return list(rows)


# --- rules -----------------------------------------------------------------------------------


async def test_a_rule_registers_the_sites_webhook(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    await connected(client, workspace)
    created = await rule(client, workspace)

    assert created["project_key"] == "API"
    assert created["template_id"] == "jira-issue-answer"
    assert created["last"] is None
    [hook] = atlassian.webhooks[ACME].values()
    assert (hook.url, hook.jql_filter) == (HOOK_URL, 'project in ("API")')
    jira = (await client.get(f"{workspace}/jira")).json()
    assert [(w["cloud_id"], w["state"], w["error"]) for w in jira["webhooks"]] == [
        (ACME, "listening", None)
    ]
    listed = (await client.get(f"{workspace}/jira/triggers")).json()["triggers"]
    assert [t["id"] for t in listed] == [created["id"]]


async def test_a_second_project_registers_the_webhook_again_and_the_last_rule_deletes_it(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    await connected(client, workspace, "10001", "10003")
    first = await rule(client, workspace)
    second = await rule(client, workspace, project_key="OPS", on="label", value="agent")
    [hook] = atlassian.webhooks[ACME].values()
    assert hook.jql_filter == 'project in ("API", "OPS")'

    for created in (first, second):
        deleted = await client.delete(f"{workspace}/jira/triggers/{created['id']}")
        assert deleted.status_code == 204
    assert atlassian.webhooks[ACME] == {}
    assert (await client.get(f"{workspace}/jira")).json()["webhooks"] == []


async def test_a_rule_on_a_project_not_picked_is_refused(
    client: AsyncClient, workspace: str
) -> None:
    await connected(client, workspace)
    refused = await client.post(
        f"{workspace}/jira/triggers", json=STATUS_RULE | {"project_key": "WEB"}
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "project_not_allowed"


async def test_a_rule_whose_workflow_cannot_run_is_refused(
    client: AsyncClient, workspace: str
) -> None:
    await connected(client, workspace)
    no_repo = await client.post(f"{workspace}/jira/triggers", json=STATUS_RULE | {"repo": None})
    unknown = await client.post(
        f"{workspace}/jira/triggers", json=STATUS_RULE | {"template_id": "no-such-template"}
    )
    for refused in (no_repo, unknown):
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "cannot_run"


async def test_a_workflow_with_no_input_cannot_be_a_rule(
    client: AsyncClient, workspace: str
) -> None:
    await connected(client, workspace)
    spec = {
        "spec_version": "0",
        "id": f"summarize-{uuid4().hex[:6]}",
        "name": "Summarize",
        "root": {"type": "agent", "id": "writer", "role": "Writer", "instructions": "Write."},
    }
    params = {"workspace_id": str(workspace_id(workspace))}
    assert (await client.post("/workflows", params=params, json={"spec": spec})).status_code == 201
    body = STATUS_RULE | {"template_id": None, "workflow": {"id": spec["id"]}, "repo": None}

    refused = await client.post(f"{workspace}/jira/triggers", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "no_input"

    # A workflow that declares a required input can be a rule's.
    with_input = spec | {
        "id": f"{spec['id']}-in",
        "input": {"required": True, "label": "Which issue?"},
    }
    stored = await client.post("/workflows", params=params, json={"spec": with_input})
    assert stored.status_code == 201, stored.text
    body["workflow"] = {"id": with_input["id"]}
    assert (await client.post(f"{workspace}/jira/triggers", json=body)).status_code == 201


async def test_a_workflow_given_a_spec_file_cannot_be_a_rule(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    """7.7: a trigger gives its run the issue key, which a spec file workflow cannot take."""
    await connected(client, workspace)
    await put_github_connection(sessions, workspace_id(workspace), 42, "acme")

    refused = await client.post(
        f"{workspace}/jira/triggers", json=STATUS_RULE | {"template_id": "sdd-spec-file"}
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "no_input"
    assert "spec file" in refused.json()["detail"]["message"]


async def test_a_rule_body_is_checked(client: AsyncClient, workspace: str) -> None:
    both = STATUS_RULE | {"workflow": {"id": "wf"}}
    spaced = STATUS_RULE | {"on": "label", "value": "two words"}
    for body in (both, spaced, STATUS_RULE | {"on": "anything"}):
        assert (await client.post(f"{workspace}/jira/triggers", json=body)).status_code == 422


async def test_a_rule_can_be_paused_and_changed(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian
) -> None:
    await connected(client, workspace)
    created = await rule(client, workspace)
    paused = await client.patch(
        f"{workspace}/jira/triggers/{created['id']}", json={"enabled": False}
    )
    assert paused.status_code == 200 and paused.json()["enabled"] is False
    assert atlassian.webhooks[ACME] == {}  # no enabled rule needs it

    changed = await client.patch(
        f"{workspace}/jira/triggers/{created['id']}", json={"enabled": True, "value": "Done"}
    )
    assert changed.json()["value"] == "Done"
    assert len(atlassian.webhooks[ACME]) == 1
    missing = await client.patch(f"{workspace}/jira/triggers/{uuid4()}", json={"enabled": False})
    assert missing.status_code == 404


async def test_statuses_are_read_from_jira(client: AsyncClient, workspace: str) -> None:
    await connected(client, workspace)
    statuses = await client.get(f"{workspace}/jira/sites/{ACME}/projects/API/statuses")
    assert statuses.json() == {"statuses": ["To Do", "In Progress", "Done"]}
    unknown = await client.get(f"{workspace}/jira/sites/{ACME}/projects/NOPE/statuses")
    assert unknown.status_code == 404


async def test_a_refused_registration_is_shown_and_audited_once(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    atlassian.refuse_webhooks = "url_conflict"
    await rule(client, workspace)
    await rule(client, workspace, value="Done")

    jira = (await client.get(f"{workspace}/jira")).json()
    assert [(w["state"], w["error"]) for w in jira["webhooks"]] == [("failed", "url_conflict")]
    async with sessions() as session:
        failed = await session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.workspace_id == workspace_id(workspace),
                AuditEvent.action == "jira.webhook_failed",
            )
        )
        assert len(list(failed)) == 1

    atlassian.refuse_webhooks = None
    await rule(client, workspace, value="To Do")
    jira = (await client.get(f"{workspace}/jira")).json()
    assert [(w["state"], w["error"]) for w in jira["webhooks"]] == [("listening", None)]


async def test_disconnecting_deletes_the_webhook(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    assert (await client.delete(f"{workspace}/connections/jira")).status_code == 204
    assert atlassian.webhooks[ACME] == {}
    async with sessions() as session:
        left = await session.scalars(
            select(JiraWebhook).where(JiraWebhook.workspace_id == workspace_id(workspace))
        )
        assert list(left) == []


# --- deliveries ------------------------------------------------------------------------------


async def test_moving_an_issue_starts_a_run_on_it(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    created = await rule(client, workspace)

    status = await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))

    assert status == 202
    [run] = await runs_of(sessions, workspace)
    assert (run.trigger, run.input, run.template_id) == ("jira", "API-1", "jira-issue-answer")
    assert run.jira_trigger_id == UUID(created["id"])
    assert run.jira_issue == {
        "cloud_id": ACME,
        "site": "acme.atlassian.net",
        "key": "API-1",
        "url": "https://acme.atlassian.net/browse/API-1",
    }
    summary = (await client.get(f"/runs/{run.id}")).json()
    assert summary["trigger"] == "jira"
    assert summary["jira_issue"] == {
        "site": "acme.atlassian.net",
        "key": "API-1",
        "url": "https://acme.atlassian.net/browse/API-1",
    }
    last = (await client.get(f"{workspace}/jira/triggers")).json()["triggers"][0]["last"]
    assert (last["outcome"], last["run_id"], last["issue_key"]) == ("started", str(run.id), "API-1")
    assert await outcomes(sessions, workspace) == ["matched"]


async def test_the_issue_text_never_reaches_the_run(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))

    [run] = await runs_of(sessions, workspace)
    assert run.input == "API-1"
    assert "Rate limit" not in str(run.jira_issue)  # the seeded issue's summary
    assert run.jira_brief is None, "the receiver reads no content; the worker reads it (7.4)"


async def test_a_run_shows_the_issue_its_agents_were_told(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))
    [run] = await runs_of(sessions, workspace)
    unread = (await client.get(f"/runs/{run.id}")).json()

    brief: dict[str, JsonValue] = {
        "key": "API-1",
        "url": "https://acme.atlassian.net/browse/API-1",
        "project": "API",
    }
    await set_run_jira_brief(sessions, run.id, brief)
    read = (await client.get(f"/runs/{run.id}")).json()

    assert unread["jira_brief"] is None
    assert read["jira_brief"]["key"] == "API-1"
    assert read["jira_brief"]["acceptance_criteria"] is None


async def test_a_retried_delivery_starts_nothing_more(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    delivery = atlassian.delivery(ACME, "API-1", status_to="In Progress", delivery_id="4242")

    assert await deliver(client, delivery) == 202
    assert await deliver(client, delivery) == 202
    assert len(await runs_of(sessions, workspace)) == 1
    assert await outcomes(sessions, workspace) == ["matched"]


async def test_a_second_move_while_the_run_goes_on_starts_nothing(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))
    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="in progress"))

    runs = await runs_of(sessions, workspace)
    assert len(runs) == 1
    last = (await client.get(f"{workspace}/jira/triggers")).json()["triggers"][0]["last"]
    assert (last["outcome"], last["run_id"]) == ("already_running", str(runs[0].id))

    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == runs[0].id).values(status="completed"))
    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))
    assert len(await runs_of(sessions, workspace)) == 2


async def test_other_moves_and_projects_start_nothing(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace, "10001", "10003")
    await rule(client, workspace)

    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="Done"))
    await deliver(client, atlassian.delivery(ACME, "API-1", labels=("", "agent")))
    await deliver(client, atlassian.delivery(ACME, "OPS-1", status_to="In Progress"))

    assert await runs_of(sessions, workspace) == []
    assert await outcomes(sessions, workspace) == ["no_match", "no_match", "no_match"]


async def test_a_project_no_longer_picked_is_dropped(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace, "10001", "10003")
    await rule(client, workspace)
    [hook_id] = atlassian.webhooks[ACME]
    await client.put(f"{workspace}/jira/sites/{ACME}/projects", json={"project_ids": ["10003"]})

    # A delivery still matching the old webhook (sent before the change reached Jira).
    await deliver(
        client, atlassian.delivery(ACME, "API-1", status_to="In Progress", webhook_ids=[hook_id])
    )
    assert await runs_of(sessions, workspace) == []


async def test_a_label_added_starts_a_run(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace, on="label", value="Agent")

    await deliver(client, atlassian.delivery(ACME, "API-1", labels=("agent", "agent backend")))
    assert await runs_of(sessions, workspace) == []  # "agent" was already there
    await deliver(client, atlassian.delivery(ACME, "API-1", labels=("backend", "backend agent")))
    assert len(await runs_of(sessions, workspace)) == 1


async def test_a_runs_own_move_starts_no_run(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    await record_jira_own_move(
        sessions, workspace_id(workspace), ACME, "API-1", "In Progress", None
    )

    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))
    assert await runs_of(sessions, workspace) == []
    assert await outcomes(sessions, workspace) == ["own_change"]


async def test_two_rules_on_one_move_start_two_runs(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    await rule(client, workspace, repo={"url": "https://github.com/acme/docs"})

    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))
    assert sorted(r.repo_url or "" for r in await runs_of(sessions, workspace)) == [
        "https://github.com/acme/app",
        "https://github.com/acme/docs",
    ]


async def test_a_start_that_is_refused_is_recorded(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)  # registers the webhook
    # A rule whose template went away since it was saved.
    broken = await create_jira_trigger(
        sessions,
        workspace_id(workspace),
        JiraTriggerFields(
            cloud_id=ACME, project_key="API", on="status", value="Done", template_id="gone"
        ),
    )
    await deliver(client, atlassian.delivery(ACME, "API-1", status_to="Done"))

    assert await runs_of(sessions, workspace) == []
    listed = (await client.get(f"{workspace}/jira/triggers")).json()["triggers"]
    last = next(t for t in listed if t["id"] == str(broken.id))["last"]
    assert last["outcome"] == "start_failed"
    assert "gone" in last["reason"]


async def test_a_delivery_for_another_workspaces_webhook_reaches_only_it(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    await deliver(
        client, atlassian.delivery(ACME, "API-1", status_to="In Progress", webhook_ids=[999_999])
    )
    assert await runs_of(sessions, workspace) == []
    assert await outcomes(sessions, workspace) == []


# --- what is refused before anything is read ---------------------------------------------------


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer not-a-jwt",
        f"Bearer {sign_delivery(ACME, secret='another-secret-long-enough-for-hs256')}",
        f"Bearer {sign_delivery(ACME, expires_in_s=-600)}",
        f"Bearer {sign_delivery(ACME, issuer='another-app')}",
    ],
)
async def test_an_unverified_delivery_is_refused_and_nothing_is_stored(
    client: AsyncClient,
    workspace: str,
    atlassian: FakeAtlassian,
    sessions: Sessions,
    authorization: str | None,
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    delivery = atlassian.delivery(ACME, "API-1", status_to="In Progress")
    headers = {k: v for k, v in delivery.headers.items() if k != "Authorization"}
    if authorization:
        headers["Authorization"] = authorization

    response = await client.post("/jira/webhooks", content=delivery.body, headers=headers)

    assert response.status_code == 401
    assert await outcomes(sessions, workspace) == []
    assert await runs_of(sessions, workspace) == []


async def test_a_body_over_the_cap_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/jira/webhooks",
        content=b"x" * 1_000_001,
        headers={"Authorization": f"Bearer {sign_delivery(ACME)}"},
    )
    assert response.status_code == 413


async def test_a_signed_delivery_that_is_not_an_issue_event_is_a_bad_request(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/jira/webhooks",
        content=b'{"webhookEvent": "jira:issue_updated", "issue": {"key": "x"}}',
        headers={
            "Authorization": f"Bearer {sign_delivery(ACME)}",
            "X-Atlassian-Webhook-Identifier": "1",
        },
    )
    assert response.status_code == 400


async def test_nothing_from_the_payload_is_logged(
    client: AsyncClient,
    workspace: str,
    atlassian: FakeAtlassian,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await connected(client, workspace)
    await rule(client, workspace)
    delivery = atlassian.delivery(ACME, "API-1", status_to="In Progress")
    with caplog.at_level(logging.DEBUG):
        await deliver(client, delivery)
    logged = caplog.text
    assert "Rate limit" not in logged  # the issue's summary
    assert delivery.headers["Authorization"].split()[1] not in logged


# --- runs started by hand from an issue (7.5) ----------------------------------------------------


def issue_workflow(kind: str = "jira_issue") -> dict[str, Any]:
    """A workflow whose input is a Jira issue's key."""
    return {
        "spec_version": "0",
        "id": "from-issue",
        "name": "From an issue",
        "input": {"required": True, "label": "Which Jira issue?", "kind": kind},
        "root": {
            "type": "agent",
            "id": "reader",
            "role": "Reader",
            "instructions": "Your input is a Jira issue key. Read the issue.",
            "tools": ["jira.getIssue"],
        },
    }


async def start_by_hand(
    client: AsyncClient, workspace: str, input: str, kind: str = "jira_issue"
) -> Any:
    return await client.post(
        "/runs",
        json={
            "workspace_id": str(workspace_id(workspace)),
            "workflow": issue_workflow(kind),
            "input": input,
            "trigger": "manual",
        },
    )


async def test_a_run_started_by_hand_from_an_issue_key_keeps_the_issue(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    await connected(client, workspace)

    started = await start_by_hand(client, workspace, " api-1 ")

    assert started.status_code == 202, started.text
    [run] = await runs_of(sessions, workspace)
    assert (run.trigger, run.jira_trigger_id) == ("manual", None)
    assert run.jira_issue == {
        "cloud_id": ACME,
        "site": "acme.atlassian.net",
        "key": "API-1",
        "url": "https://acme.atlassian.net/browse/API-1",
    }
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == run.id).values(status="failed"))
    rerun = await client.post(f"/runs/{run.id}/rerun")
    assert rerun.status_code == 202, rerun.text
    again = (await client.get(f"/runs/{rerun.json()['run_id']}")).json()
    assert again["jira_issue"]["key"] == "API-1"


async def test_a_text_input_is_not_read_as_an_issue(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    await connected(client, workspace)

    started = await start_by_hand(client, workspace, "API-1", kind="text")

    assert started.status_code == 202, started.text
    [run] = await runs_of(sessions, workspace)
    assert run.jira_issue is None


@pytest.mark.parametrize(
    ("input", "status", "code"),
    [
        ("fix the login page", 422, "issue_invalid"),
        ("OPS-3", 422, "project_not_allowed"),
    ],
)
async def test_a_run_by_hand_needs_an_issue_of_a_picked_project(
    client: AsyncClient, workspace: str, sessions: Sessions, input: str, status: int, code: str
) -> None:
    await connected(client, workspace)

    started = await start_by_hand(client, workspace, input)

    assert started.status_code == status
    assert str(started.json()["detail"]).startswith(code)
    assert await runs_of(sessions, workspace) == []


async def test_a_run_by_hand_from_an_issue_needs_jira(
    client: AsyncClient, workspace: str, sessions: Sessions
) -> None:
    started = await start_by_hand(client, workspace, "API-1")

    assert started.status_code == 409
    assert str(started.json()["detail"]).startswith("jira_not_connected")


async def test_moving_an_issue_starts_the_sdd_template_on_it(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    """AC-5's start (7.5): a rule for "Build from a Jira issue" starts it on the moved issue."""
    await connected(client, workspace)
    await put_github_connection(sessions, workspace_id(workspace), 42, "acme")
    await rule(client, workspace, template_id="sdd")

    status = await deliver(client, atlassian.delivery(ACME, "API-1", status_to="In Progress"))

    assert status == 202
    [run] = await runs_of(sessions, workspace)
    assert (run.trigger, run.input, run.template_id) == ("jira", "API-1", "sdd")
    assert run.jira_issue is not None and run.jira_issue["key"] == "API-1"
    spec = cast(dict[str, Any], run.spec)
    steps = [step["id"] for step in spec["root"]["steps"]]
    assert steps[:2] == ["spec_loop", "clarify"]
