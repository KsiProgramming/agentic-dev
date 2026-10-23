"""`open_repo_tools` routes each node's calls: readers to the shared checkout, each writer to
its own worktree (fake and Docker sandboxes, see conftest)."""

import asyncio
import re
from uuid import UUID

import pytest
from pydantic import JsonValue

from agentic_runtime import AgentRequest, ClaudeRuntime, ToolResult
from agentic_runtime.testing import MockClaude, collect_and_check, text_reply, tool_use_reply
from agentic_sandbox import Sandbox
from agentic_tools.repo import READ_TOOL_NAMES, WRITE_TOOL_NAMES, open_repo_tools

READS = sorted(READ_TOOL_NAMES)


async def sh(box: Sandbox, script: str) -> tuple[int, str]:
    result = await box.exec(["sh", "-c", script])
    return result.exit_code, (result.stdout + result.stderr).strip()


def write(path: str, content: str = "x\n") -> dict[str, JsonValue]:
    return {"path": path, "content": content}


async def test_a_run_without_writers_offers_only_the_read_tools(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        names = sorted(d.name for d in tools.definitions())
        output = await tools.call("repo.write_file", write("x"), node_id="reader")

    assert names == READS
    assert (output.is_error, output.text) == (True, "unknown tool: repo.write_file")


async def test_a_run_with_writers_also_offers_the_write_tools(
    sandbox: Sandbox, run_id: UUID
) -> None:
    async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
        definitions = {d.name: d for d in tools.definitions()}

    assert sorted(definitions) == sorted([*READS, *WRITE_TOOL_NAMES])
    assert definitions["repo.commit"].input_schema["examples"] == [{"message": "Add NOTES.md"}]


async def test_a_writer_reads_its_own_writes_and_nobody_else_sees_them(
    sandbox: Sandbox, run_id: UUID
) -> None:
    async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
        wrote = await tools.call("repo.write_file", write("NOTES.md", "mine\n"), node_id="writer")
        own = await tools.call("repo.read_file", {"path": "NOTES.md"}, node_id="writer")
        reader = await tools.call("repo.read_file", {"path": "NOTES.md"}, node_id="reader")
        anonymous = await tools.call("repo.read_file", {"path": "NOTES.md"})

    assert not wrote.is_error
    assert (own.is_error, own.text) == (False, "1\tmine")
    assert reader.is_error and "no such path" in reader.text
    assert anonymous.is_error and "no such path" in anonymous.text
    assert (await sh(sandbox, "test -e NOTES.md"))[0] == 1


async def test_only_writers_may_write(sandbox: Sandbox, run_id: UUID) -> None:
    async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
        written = await tools.call("repo.write_file", write("x.txt"), node_id="reader")
        committed = await tools.call("repo.commit", {"message": "m"}, node_id="reader")

    assert (written.is_error, written.text) == (True, "unknown tool: repo.write_file")
    assert (committed.is_error, committed.text) == (True, "unknown tool: repo.commit")


async def test_each_writer_gets_one_worktree_on_its_branch(sandbox: Sandbox, run_id: UUID) -> None:
    async with open_repo_tools(sandbox, run_id=run_id, writers={"one", "two"}) as tools:
        for node_id in ("one", "two", "one", "two"):
            await tools.call("repo.write_file", write(f"{node_id}.txt"), node_id=node_id)
        one = await tools.call("repo.commit", {"message": "one"}, node_id="one")
        two = await tools.call("repo.list_files", {}, node_id="two")

    assert re.fullmatch(rf"[0-9a-f]+ on agent/{run_id}/one: one\.txt", one.text)
    assert "one.txt" not in two.text.splitlines()
    assert "two.txt" in two.text.splitlines()
    code, branches = await sh(sandbox, "git -c safe.directory=* worktree list --porcelain")
    assert code == 0
    assert sorted(re.findall(r"branch refs/heads/(agent/\S+)", branches)) == [
        f"agent/{run_id}/one",
        f"agent/{run_id}/two",
    ]


async def test_a_worktree_that_cannot_be_made_is_an_error_result(
    sandbox: Sandbox, run_id: UUID
) -> None:
    assert (await sh(sandbox, f"mkdir '{sandbox.worktrees_dir}/writer'"))[0] == 0

    async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
        output = await tools.call("repo.write_file", write("x.txt"), node_id="writer")

    assert (output.is_error, output.text) == (
        True,
        "the worktree of node writer is on another branch",
    )


async def test_writers_need_the_run_id(sandbox: Sandbox) -> None:
    with pytest.raises(ValueError, match="run id"):
        async with open_repo_tools(sandbox, writers={"writer"}):
            pass


async def test_every_client_closes_when_the_run_fails(sandbox: Sandbox, run_id: UUID) -> None:
    # Each MCP client's task group wraps the error on its way out.
    with pytest.RaisesGroup(pytest.RaisesExc(RuntimeError, match="boom"), flatten_subgroups=True):
        async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
            await tools.call("repo.write_file", write("x.txt"), node_id="writer")
            raise RuntimeError("boom")

    # The sandbox is still usable after the tools closed.
    assert (await sh(sandbox, "true"))[0] == 0


async def test_every_client_closes_when_the_run_is_cancelled(
    sandbox: Sandbox, run_id: UUID
) -> None:
    opened = asyncio.Event()

    async def use() -> None:
        async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
            await tools.call("repo.write_file", write("x.txt"), node_id="writer")
            opened.set()
            await asyncio.sleep(30)

    task = asyncio.create_task(use())
    await opened.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_claude_commits_on_its_branch_through_the_tools(
    sandbox: Sandbox, run_id: UUID
) -> None:
    """With a scripted Claude: the writer's calls carry its node id to its worktree."""
    mock = MockClaude(
        [
            tool_use_reply(
                ("toolu_1", "repo__write_file", {"path": "NOTES.md", "content": "hi\n"}),
                ("toolu_2", "repo__commit", {"message": "Add NOTES.md"}),
            ),
            text_reply("Done."),
        ]
    )
    request = AgentRequest(
        node_id="writer",
        role="Writer",
        instructions="Add a NOTES.md and commit it.",
        tools=["repo.write_file", "repo.commit"],
    )

    async with open_repo_tools(sandbox, run_id=run_id, writers={"writer"}) as tools:
        events = await collect_and_check(ClaudeRuntime(mock.client, tools=tools), request)

    results = [e for e in events if isinstance(e, ToolResult)]
    assert [r.is_error for r in results] == [False, False]
    assert re.fullmatch(rf"[0-9a-f]+ on agent/{run_id}/writer: NOTES\.md", results[1].output)
