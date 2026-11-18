"""A run that asked a question waits for the answer (7.9): the comment webhook and "Check now"
resume it, the platform's own comment does not, and nothing is built meanwhile."""

from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_api import create_app
from agentic_api.settings import Settings
from agentic_engine.agent import IssueBrief, RunContext
from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_jira import FakeAtlassian
from agentic_runtime import ToolOutput
from agentic_runtime.fake import FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor
from agentic_secrets import generate_key_file
from agentic_store import JiraDelivery, PostgresEventSink, Run, create_run, max_event_seq

pytestmark = pytest.mark.integration

ACME = "fake-cloud-acme"
KEY = "API-1"
BRIEF = IssueBrief(key=KEY, url="https://acme.atlassian.net/browse/API-1", project="API")
ISSUE = {"cloud_id": ACME, "site": "acme.atlassian.net", "key": KEY, "url": BRIEF.url}
RULE = {
    "cloud_id": ACME,
    "project_key": "API",
    "on": "status",
    "value": "In Progress",
    "template_id": "jira-issue-answer",
    "repo": {"url": "https://github.com/acme/app"},
}
Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
def atlassian() -> FakeAtlassian:
    return FakeAtlassian("http://test")


@pytest.fixture
async def client(
    postgres_url: str, redis_url: str, tmp_path: Path, atlassian: FakeAtlassian, sessions: Sessions
) -> AsyncIterator[AsyncClient]:
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
    created = await client.post("/workspaces", json={"name": f"ans-{uuid4().hex[:8]}"})
    assert created.status_code == 201
    return f"/workspaces/{created.json()['id']}"


async def connected(client: AsyncClient, workspace: str) -> None:
    started = await client.post(f"{workspace}/connections/jira/authorize")
    url = urlsplit(str(started.json()["authorize_url"]))
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (await client.get(url.path, params=params)).status_code == 303
    picked = await client.put(
        f"{workspace}/jira/sites/{ACME}/projects", json={"project_ids": ["10001"]}
    )
    assert picked.status_code == 200, picked.text


def spec() -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "waits",
            "name": "Waits",
            "root": {
                "type": "sequence",
                "id": "main",
                "steps": [
                    {"type": "gate", "id": "post", "title": "Post?"},
                    {
                        "type": "tool",
                        "id": "ask",
                        "tool": "jira.comment",
                        "args": {"issue_from": "request", "body": "Which one?"},
                    },
                    {"type": "wait_for", "id": "wait", "title": "Waiting", "after_from": "ask"},
                    {"type": "agent", "id": "build", "role": "B", "instructions": "Go."},
                ],
            },
        }
    )


class Asked:
    """A run paused at its `wait_for`, the question posted on the fake Jira issue."""

    def __init__(self, sessions: Sessions, workspace: str, atlassian: FakeAtlassian) -> None:
        self.sessions = sessions
        self.workspace_id = UUID(workspace.rsplit("/", 1)[1])
        self.atlassian = atlassian
        self.runtime = FakeRuntime({})
        self.workflow = spec()
        self.run_id: UUID

    async def start(self) -> None:
        """Post the question as the connected account, then pause at the wait."""
        question = await self.atlassian.add_comment(
            SecretStr("fake-jira-access-0001"), ACME, KEY, "Which one?"
        )
        self.run_id = await create_run(
            self.sessions, self.workflow, KEY, workspace_id=self.workspace_id, jira_issue=ISSUE
        )
        self.common = {
            "run_id": self.run_id,
            "sink": PostgresEventSink(self.sessions),
            "checkpointer": InMemorySaver(serde=checkpoint_serde()),
            "tools": ScriptedToolExecutor(
                {"jira.comment": ToolOutput(text="posted", data={"comment_id": question})}
            ),
            "context": RunContext(request=KEY).model_copy(update={"issue": BRIEF}),
        }
        first = await run_workflow(self.workflow, self.runtime, KEY, **self.common)  # type: ignore[arg-type]
        assert first.waiting_at == "post"
        second = await resume_workflow(
            self.workflow,
            self.runtime,
            KEY,
            next_seq=await max_event_seq(self.sessions, self.run_id) + 1,
            attempt=2,
            decision=GateDecision(decision="approve"),
            **self.common,  # type: ignore[arg-type]
        )
        assert second.waiting_at == "wait"

    async def status(self) -> str:
        async with self.sessions() as session:
            run = await session.get(Run, self.run_id)
        assert run is not None
        return run.status


async def outcomes(sessions: Sessions, workspace_id: UUID) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(JiraDelivery.outcome)
            .where(JiraDelivery.workspace_id == workspace_id)
            .order_by(JiraDelivery.id)
        )
        return [r for r in rows if r]


async def deliver(
    client: AsyncClient, atlassian: FakeAtlassian, comment_id: str, author: str
) -> int:
    delivery = atlassian.comment_delivery(ACME, KEY, comment_id, author_id=author)
    response = await client.post("/jira/webhooks", content=delivery.body, headers=delivery.headers)
    return response.status_code


@pytest.fixture
async def asked(
    client: AsyncClient, workspace: str, atlassian: FakeAtlassian, sessions: Sessions
) -> Asked:
    await connected(client, workspace)
    # A rule makes the platform register the site's webhook, which comment events share.
    created = await client.post(f"{workspace}/jira/triggers", json=RULE)
    assert created.status_code == 201, created.text
    waiting = Asked(sessions, workspace, atlassian)
    await waiting.start()
    return waiting


async def test_the_run_holds_after_the_question(asked: Asked, client: AsyncClient) -> None:
    assert await asked.status() == "waiting"
    shown = (await client.get(f"/runs/{asked.run_id}")).json()["waiting_gate"]
    assert shown["node_id"] == "wait"
    assert shown["wait_for"]["issue"]["key"] == KEY


async def test_a_comment_from_someone_else_resumes_the_run(
    asked: Asked, client: AsyncClient, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    answer = atlassian.reply(ACME, KEY, "Per API key.")

    assert await deliver(client, atlassian, answer, "someone-else") == 202

    assert (await outcomes(sessions, asked.workspace_id))[-1] == "answered"
    assert await asked.status() == "queued"


async def test_the_platforms_own_comment_does_not_resume_the_run(
    asked: Asked, client: AsyncClient, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    own = await atlassian.add_comment(SecretStr("fake-jira-access-0001"), ACME, KEY, "more")

    assert await deliver(client, atlassian, own, "fake-account-1") == 202

    assert await asked.status() == "waiting"
    assert (await outcomes(sessions, asked.workspace_id))[-1] == "own_comment"


async def test_a_comment_older_than_the_question_does_not_resume_the_run(
    asked: Asked, client: AsyncClient, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    assert await deliver(client, atlassian, "1", "someone-else") == 202

    assert await asked.status() == "waiting"
    assert (await outcomes(sessions, asked.workspace_id))[-1] == "no_waiting_run"


async def test_a_retried_delivery_resumes_the_run_once(
    asked: Asked, client: AsyncClient, atlassian: FakeAtlassian, sessions: Sessions
) -> None:
    answer = atlassian.reply(ACME, KEY, "Per API key.")
    delivery = atlassian.comment_delivery(ACME, KEY, answer, delivery_id="777")

    for _ in range(2):
        sent = await client.post("/jira/webhooks", content=delivery.body, headers=delivery.headers)
        assert sent.status_code == 202

    assert (await outcomes(sessions, asked.workspace_id)).count("answered") == 1


async def test_check_now_finds_an_answer_without_a_webhook(
    asked: Asked, client: AsyncClient, atlassian: FakeAtlassian
) -> None:
    checked = await client.post(f"/runs/{asked.run_id}/answers/check")
    assert checked.status_code == 200 and checked.json()["found"] is False
    assert await asked.status() == "waiting"

    atlassian.reply(ACME, KEY, "Per API key.")
    checked = await client.post(f"/runs/{asked.run_id}/answers/check")

    assert checked.json()["found"] is True
    assert await asked.status() == "queued"


async def test_check_now_ignores_the_platforms_own_comments(
    asked: Asked, client: AsyncClient, atlassian: FakeAtlassian
) -> None:
    await atlassian.add_comment(SecretStr("fake-jira-access-0001"), ACME, KEY, "a second note")

    checked = await client.post(f"/runs/{asked.run_id}/answers/check")

    assert checked.json()["found"] is False
    assert await asked.status() == "waiting"


async def test_check_now_on_a_run_that_is_not_waiting_is_a_conflict(client: AsyncClient) -> None:
    assert (await client.post(f"/runs/{uuid4()}/answers/check")).status_code == 404


async def test_a_person_cannot_approve_a_wait(asked: Asked, client: AsyncClient) -> None:
    response = await client.post(
        f"/runs/{asked.run_id}/approvals", json={"node_id": "wait", "decision": "approve"}
    )

    assert response.status_code == 409
    assert await asked.status() == "waiting"
