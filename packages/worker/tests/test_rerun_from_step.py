"""Rerun from a step (12.4) on a worker: the new run's fresh sandbox holds the original writer's
commit on its own branch, the steps before the chosen one are not run again, and the step runs
with its edited instructions."""

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.graph import checkpoint_serde
from agentic_runtime import AgentRequest, Failed, ToolExecutor
from agentic_runtime.fake import FakeRuntime
from agentic_sandbox import RepoSource
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import make_repo
from agentic_store import (
    RerunFromStep,
    create_rerun,
    enqueue_run,
    get_run,
    list_run_events,
    list_saved_branches,
)
from agentic_tools.repo import COMMIT_AUTHOR

from .test_worker import (
    BranchLog,
    RecordingSandboxes,
    commit_then,
    docker_or_skip,
    notes_writer,
    scripted,
    submit,
    wait_for_status,
    worker,
)

pytestmark = pytest.mark.integration

REVIEWER = {"type": "agent", "id": "reviewer", "role": "R", "instructions": "Reject it."}


async def queue(redis_url: str, run_id: UUID) -> None:
    redis = Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await enqueue_run(redis, run_id)
    finally:
        await redis.aclose()


async def test_done_when_a_rerun_from_the_failed_step_keeps_the_writer_s_commit(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str, redis_url: str, tmp_path: Path
) -> None:
    """Done when (12.4): a run that failed at its last step is rerun from that step with changed
    instructions; the writer does not run again, and the new run's branch holds its commit."""
    client = docker_or_skip()
    repos = tmp_path / "repos"
    make_repo(repos / "hello")
    repo = RepoSource(url=str(repos / "hello"))
    spec = commit_then(REVIEWER)
    checkpointer = InMemorySaver(serde=checkpoint_serde())
    first = scripted({"writer": notes_writer(), "reviewer": [Failed(error="rejected")]})
    async with worker(
        postgres_url,
        redis_url,
        make_runtime=first,
        sandboxes=DockerSandboxManager(client, local_root=repos),
        checkpointer=checkpointer,
    ):
        original = await submit(sessions, redis_url, spec, repo)
        await wait_for_status(sessions, original, "failed")
    [saved] = await list_saved_branches(sessions, original)

    rerun_id = await create_rerun(
        sessions,
        original,
        from_step=RerunFromStep(node_id="reviewer", set_params=[("instructions", "Approve it.")]),
    )
    requests: list[AgentRequest] = []

    def second(tools: ToolExecutor | None) -> FakeRuntime:
        runtime = FakeRuntime({}, tools=tools)
        runtime.requests = requests
        return runtime

    branch_log = BranchLog()
    sandboxes = RecordingSandboxes(
        DockerSandboxManager(client, local_root=repos), inspect=branch_log
    )
    async with worker(
        postgres_url,
        redis_url,
        make_runtime=second,
        sandboxes=sandboxes,
        checkpointer=checkpointer,
    ):
        await queue(redis_url, rerun_id)
        await wait_for_status(sessions, rerun_id, "completed")
        await asyncio.wait_for(sandboxes.closed.wait(), 30)

    # Only the reviewer ran, with its new instructions.
    assert [r.node_id for r in requests] == ["reviewer"]
    assert requests[0].instructions.startswith("Approve it.")
    # The writer's commit is on the new run's own branch, restored from the original's bundle.
    branch = f"agent/{rerun_id}/writer"
    name, email = COMMIT_AUTHOR
    assert branch_log.branches == [branch]
    assert branch_log.commits == [f"{name} <{email}>|Add NOTES.md", "NOTES.md"]
    events = await list_run_events(sessions, rerun_id)
    [restored] = [e for e in events if e.type == "branches_restored"]
    assert restored.payload == {"branches": [{"branch": branch, "head": saved.head_sha}]}
    [started] = [e for e in events if e.type == "run_started"]
    assert started.payload["rerun_from"] == {"run_id": str(original), "node_id": "reviewer"}
    assert started.payload["carried"] == ["writer"]
    assert not [e for e in events if e.type == "node_started" and e.node_id == "writer"]
    rerun = await get_run(sessions, rerun_id)
    source = await get_run(sessions, original)
    assert rerun is not None and source is not None
    assert rerun.base_sha == source.base_sha
    assert source.status == "failed"  # the original is unchanged
