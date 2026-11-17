"""The issue brief of a Jira-triggered run (7.4): read once, on the run's first attempt, through
the same reader as `jira.getIssue`, stored on the run and told to every agent; reused by its
resumes and by a rerun from a step; a failure ends the run before any step."""

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_jira import FAKE_AC_FIELD, FAKE_POINTS_FIELD, FakeAtlassian
from agentic_runtime import AgentRequest, ToolExecutor
from agentic_runtime.fake import FakeRuntime
from agentic_store import (
    JiraMappedField,
    JiraOrigin,
    JiraTriggerFields,
    RerunFromStep,
    create_jira_trigger,
    create_rerun,
    create_run,
    enqueue_run,
    get_run,
    list_run_events,
    record_approval,
    set_jira_project_fields,
)

from .test_worker import jira_workspace, master_key, submit, wait_for_status, worker

pytestmark = pytest.mark.integration

__all__ = ["master_key"]  # a fixture

Sessions = async_sessionmaker[AsyncSession]
ACME = "fake-cloud-acme"
CRITERIA = "- A client over 100 requests a minute **gets 429.**\n- The limit is per API key."
SPEC = parse_spec(
    {
        "spec_version": "0",
        "id": "brief",
        "name": "Write, approve, review",
        "input": {"required": True, "label": "Jira issue key"},
        "root": {
            "type": "sequence",
            "id": "main",
            "steps": [
                {"type": "agent", "id": "writer", "role": "W", "instructions": "Write the spec."},
                {"type": "gate", "id": "approve", "title": "Approve the spec"},
                {"type": "agent", "id": "reviewer", "role": "R", "instructions": "Review it."},
            ],
        },
    }
)


class Agents:
    """Every run's agents echo; their requests are kept, across workers."""

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []

    def __call__(self, tools: ToolExecutor | None) -> FakeRuntime:
        runtime = FakeRuntime({}, tools=tools)
        runtime.requests = self.requests
        return runtime

    def context_of(self, node_id: str) -> list[str]:
        return [r.context for r in self.requests if r.node_id == node_id]


async def queue(redis_url: str, run_id: UUID) -> None:
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()


async def triggered(
    sessions: Sessions, redis_url: str, workspace_id: UUID, key: str, spec: WorkflowSpec = SPEC
) -> UUID:
    """A run a trigger started on issue `key`, queued."""
    rule = await create_jira_trigger(
        sessions,
        workspace_id,
        JiraTriggerFields(
            cloud_id=ACME, project_key="API", on="status", value="Ready", template_id="t"
        ),
    )
    run_id = await create_run(
        sessions,
        spec,
        key,
        workspace_id=workspace_id,
        jira_origin=JiraOrigin(
            trigger_id=rule.id,
            delivery_row=None,
            delivery_id=f"d-{key}",
            issue={
                "cloud_id": ACME,
                "site": "acme.atlassian.net",
                "key": key,
                "url": f"https://acme.atlassian.net/browse/{key}",
            },
        ),
    )
    await queue(redis_url, run_id)
    return run_id


async def mapped_workspace(sessions: Sessions, atlassian: FakeAtlassian, master_key: Path) -> UUID:
    workspace_id = await jira_workspace(sessions, atlassian, master_key)
    await set_jira_project_fields(
        sessions,
        workspace_id,
        ACME,
        "API",
        [
            JiraMappedField("acceptance_criteria", FAKE_AC_FIELD, "Acceptance criteria"),
            JiraMappedField("story_points", FAKE_POINTS_FIELD, "Story point estimate"),
        ],
    )
    return workspace_id


async def test_every_agent_is_told_the_issue_read_once(
    sessions: Sessions, postgres_url: str, redis_url: str, master_key: Path
) -> None:
    """Done when (7.4), on the worker: the brief holds the mapped acceptance criteria, story
    points and components; it is read once and reused across a gate's resume, and by a rerun
    from a step; a rerun from the beginning reads the issue again."""
    atlassian = FakeAtlassian("")
    workspace_id = await mapped_workspace(sessions, atlassian, master_key)
    agents = Agents()
    checkpointer = InMemorySaver(serde=checkpoint_serde())

    def working() -> AbstractAsyncContextManager[object]:
        return worker(
            postgres_url,
            redis_url,
            make_runtime=agents,
            master_key_file=master_key,
            jira=atlassian,
            checkpointer=checkpointer,
        )

    async with working():
        run_id = await triggered(sessions, redis_url, workspace_id, "API-1")
        await wait_for_status(sessions, run_id, "waiting")
        await record_approval(sessions, run_id, "approve", GateDecision(decision="approve"))
        await queue(redis_url, run_id)
        await wait_for_status(sessions, run_id, "completed")

    [writer] = agents.context_of("writer")
    [reviewer] = agents.context_of("reviewer")
    assert writer == reviewer
    assert "<jira-issue>\n# API-1: Rate limit the public endpoints" in writer
    assert f"## Acceptance criteria\n\n{CRITERIA}" in writer
    assert "- Story points: 5" in writer and "- Components: gateway" in writer
    assert writer.index("<request>\nAPI-1\n</request>") < writer.index("<jira-issue>")
    assert atlassian.issue_reads == [(ACME, "API-1")], "read once, before the first step"
    stored = await get_run(sessions, run_id)
    assert stored is not None and stored.jira_brief is not None
    assert stored.jira_brief["acceptance_criteria"] == CRITERIA

    from_step = await create_rerun(sessions, run_id, from_step=RerunFromStep(node_id="reviewer"))
    again = await create_rerun(sessions, run_id)
    async with working():
        await queue(redis_url, from_step)
        await wait_for_status(sessions, from_step, "completed")
        assert atlassian.issue_reads == [(ACME, "API-1")], "a rerun from a step reuses it"
        await queue(redis_url, again)
        await wait_for_status(sessions, again, "waiting")
    assert atlassian.issue_reads == [(ACME, "API-1")] * 2, "a rerun from the start reads it"
    assert agents.context_of("reviewer")[1] == reviewer


@pytest.mark.parametrize(
    ("key", "reason"),
    [("OPS-1", "project_not_allowed: "), ("API-404", "issue_not_found: ")],
)
async def test_an_issue_that_cannot_be_read_fails_the_run_before_any_step(
    sessions: Sessions, postgres_url: str, redis_url: str, master_key: Path, key: str, reason: str
) -> None:
    atlassian = FakeAtlassian("")
    workspace_id = await mapped_workspace(sessions, atlassian, master_key)
    agents = Agents()

    async with worker(
        postgres_url, redis_url, make_runtime=agents, master_key_file=master_key, jira=atlassian
    ):
        run_id = await triggered(sessions, redis_url, workspace_id, key)
        await wait_for_status(sessions, run_id, "failed")

    events = await list_run_events(sessions, run_id)
    assert [e.type for e in events] == ["run_started", "run_failed"]
    assert events[-1].payload is not None
    assert str(events[-1].payload["error"]).startswith(reason)
    assert agents.requests == []
    stored = await get_run(sessions, run_id)
    assert stored is not None and stored.jira_brief is None


async def test_a_run_no_trigger_started_reads_no_issue(
    sessions: Sessions, postgres_url: str, redis_url: str, master_key: Path
) -> None:
    atlassian = FakeAtlassian("")
    agents = Agents()

    async with worker(
        postgres_url, redis_url, make_runtime=agents, master_key_file=master_key, jira=atlassian
    ):
        run_id = await submit(sessions, redis_url, SPEC)
        await wait_for_status(sessions, run_id, "waiting")

    assert atlassian.issue_reads == []
    [writer] = agents.context_of("writer")
    assert "<jira-issue>" not in writer
