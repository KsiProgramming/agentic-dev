"""`repo.diff` and `node` on the reads (13.1): a step reads the work of writers that ran before it,
from git refs, and nothing else."""

import re
from uuid import UUID

from agentic_runtime import ReadableWriter, ReadableWriters
from agentic_sandbox import Sandbox, add_worktree, branch_name
from agentic_tools.repo import open_repo_tools

_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"


async def sh(box: Sandbox, script: str) -> str:
    result = await box.exec(["sh", "-c", script])
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def said(text: str) -> str:
    """A refusal's own text, without the MCP prefix."""
    return re.sub(r"^Error executing tool \w+: ", "", text)


def readable(
    run_id: UUID,
    *completed: str,
    known: tuple[str, ...] = ("test_writer", "refactorer"),
    integration: tuple[str, ...] = (),
) -> ReadableWriters:
    writers = ReadableWriters(lambda node: branch_name(run_id, node))
    writers.set(
        [ReadableWriter(n, "integration" if n in integration else "writer") for n in completed],
        known=known,
    )
    return writers


async def commit_as(sandbox: Sandbox, run_id: UUID, node: str, script: str) -> None:
    tree = await add_worktree(sandbox, run_id, node)
    await sh(tree, f"{script} && {_COMMIT} commit -q -m work")


async def test_a_reviewer_reads_the_changes_of_a_writer(sandbox: Sandbox, run_id: UUID) -> None:
    await commit_as(
        sandbox,
        run_id,
        "test_writer",
        "mkdir tests && printf 'def test_a():\\n    pass\\n' > tests/t.py",
    )
    async with open_repo_tools(sandbox, readable=readable(run_id, "test_writer")) as tools:
        output = await tools.call("repo.diff", {"node": "test_writer"}, node_id="reviewer")

    assert not output.is_error
    assert output.text.startswith("test_writer changed 1 file (+2 -0) against the run's base ")
    assert "added tests/t.py (+2 -0)" in output.text
    assert "+def test_a():" in output.text


async def test_the_reads_with_node_see_committed_work_only(sandbox: Sandbox, run_id: UUID) -> None:
    await commit_as(sandbox, run_id, "test_writer", "printf 'committed\\n' > notes.md")
    await sh(await add_worktree(sandbox, run_id, "test_writer"), "printf 'draft\\n' > draft.md")
    async with open_repo_tools(sandbox, readable=readable(run_id, "test_writer")) as tools:
        read = await tools.call("repo.read_file", {"path": "notes.md", "node": "test_writer"})
        listed = await tools.call("repo.list_files", {"node": "test_writer"})
        found = await tools.call("repo.search", {"pattern": "committed", "node": "test_writer"})
        draft = await tools.call("repo.read_file", {"path": "draft.md", "node": "test_writer"})
        plain = await tools.call("repo.read_file", {"path": "notes.md"})

    assert read.text == "1\tcommitted"
    assert "notes.md" in listed.text.splitlines()
    assert "draft.md" not in listed.text
    assert found.text == "notes.md:1: committed"
    assert (draft.is_error, said(draft.text)) == (True, "no such path in the repository: draft.md")
    assert plain.is_error  # without node, the run's checkout has none of it


async def test_every_refusal_is_one_fixed_text(sandbox: Sandbox, run_id: UUID) -> None:
    await commit_as(sandbox, run_id, "test_writer", "echo x > x.txt")
    await add_worktree(sandbox, run_id, "empty")  # a branch with no commit
    state = readable(run_id, "test_writer", "empty", known=("test_writer", "empty", "late"))
    async with open_repo_tools(sandbox, readable=state) as tools:
        refused = {
            node: said((await tools.call("repo.diff", {"node": node})).text)
            for node in ("nobody", "late", "empty", "orch.t1")
        }
        read = await tools.call("repo.read_file", {"path": "x.txt", "node": "late"})

    assert refused == {
        "nobody": "'nobody' is not a writer of this run",
        "late": "writer 'late' has not run before this step",
        "empty": "writer 'empty' has no commits",
        "orch.t1": "'orch.t1' is not a writer of this run",
    }
    assert read.is_error
    assert said(read.text) == "writer 'late' has not run before this step"


async def test_a_run_without_readable_writers_refuses_node(sandbox: Sandbox) -> None:
    async with open_repo_tools(sandbox) as tools:
        output = await tools.call("repo.diff", {"node": "test_writer"})

    assert (output.is_error, said(output.text)) == (
        True,
        "'test_writer' is not a writer of this run",
    )


async def test_a_writer_reads_an_earlier_writer_and_still_writes_its_own_branch(
    sandbox: Sandbox, run_id: UUID
) -> None:
    await commit_as(sandbox, run_id, "test_writer", "printf 'def test_a(): pass\\n' > test_a.py")
    state = readable(run_id, "test_writer")
    async with open_repo_tools(
        sandbox, run_id=run_id, writers={"refactorer"}, readable=state
    ) as tools:
        theirs = await tools.call(
            "repo.read_file", {"path": "test_a.py", "node": "test_writer"}, node_id="refactorer"
        )
        await tools.call(
            "repo.write_file", {"path": "src.py", "content": "x = 1\n"}, node_id="refactorer"
        )
        own = await tools.call(
            "repo.read_file", {"path": "src.py", "node": "refactorer"}, node_id="refactorer"
        )
        committed = await tools.call("repo.commit", {"message": "m"}, node_id="refactorer")
        own_diff = await tools.call("repo.diff", {"node": "refactorer"}, node_id="refactorer")

    assert theirs.text == "1\tdef test_a(): pass"
    assert own.text == "1\tx = 1"  # naming itself reads its worktree, as without node
    assert committed.text.endswith(f"on {branch_name(run_id, 'refactorer')}: src.py")
    # A writer has not completed before its own step: its diff is refused.
    assert said(own_diff.text) == "writer 'refactorer' has not run before this step"


async def test_node_set_to_an_orchestrator_reads_its_integration_branch(
    sandbox: Sandbox, run_id: UUID
) -> None:
    await commit_as(sandbox, run_id, "build", "printf 'merged\\n' > team.md")
    state = readable(run_id, "build", known=("build",), integration=("build",))
    async with open_repo_tools(sandbox, readable=state) as tools:
        diff = await tools.call("repo.diff", {"node": "build"}, node_id="reviewer")

    assert "added team.md (+1 -0)" in diff.text


async def test_repo_diff_works_when_the_worktree_is_gone_after_a_restore(
    sandbox: Sandbox, run_id: UUID
) -> None:
    await commit_as(sandbox, run_id, "test_writer", "echo kept > kept.txt")
    tree = await add_worktree(sandbox, run_id, "test_writer")
    await sh(sandbox, f"git -c safe.directory=* worktree remove --force '{tree.path}'")

    async with open_repo_tools(sandbox, readable=readable(run_id, "test_writer")) as tools:
        output = await tools.call("repo.diff", {"node": "test_writer"})

    assert not output.is_error
    assert "added kept.txt (+1 -0)" in output.text


async def test_a_long_diff_is_cut_and_names_the_way_to_read_one_file(
    sandbox: Sandbox, run_id: UUID
) -> None:
    from agentic_tools.repo import RepoLimits

    await commit_as(
        sandbox,
        run_id,
        "test_writer",
        'i=0; while [ $i -lt 300 ]; do echo "line $i"; i=$((i+1)); done > big.txt'
        " && echo small > small.txt",
    )
    async with open_repo_tools(
        sandbox, readable=readable(run_id, "test_writer"), limits=RepoLimits(max_bytes=600)
    ) as tools:
        output = await tools.call("repo.diff", {"node": "test_writer"})
        one = await tools.call("repo.diff", {"node": "test_writer", "path": "small.txt"})

    assert "(truncated at 0 KB: call again with path to read one file)" in output.text
    assert "+small" in one.text
    assert "big.txt" not in one.text


async def test_a_hub_reading_as_its_orchestrator_can_still_name_a_writer(
    sandbox: Sandbox, run_id: UUID
) -> None:
    """The 6.9 reroute sends the hub's plain reads to the integration branch; `node` reaches the
    same refs from that server too."""
    await commit_as(sandbox, run_id, "test_writer", "printf 'tests\n' > tests.md")
    await commit_as(sandbox, run_id, "build", "printf 'merged\n' > team.md")
    state = readable(run_id, "test_writer", known=("test_writer", "build"))
    async with open_repo_tools(
        sandbox, run_id=run_id, task_writers={"build"}, readable=state
    ) as tools:
        plain = await tools.call("repo.read_file", {"path": "team.md"}, node_id="build")
        named = await tools.call(
            "repo.read_file", {"path": "tests.md", "node": "test_writer"}, node_id="build"
        )
        diff = await tools.call("repo.diff", {"node": "test_writer"}, node_id="build")

    assert plain.text == "1\tmerged"  # as before: the integration branch
    assert named.text == "1\ttests"
    assert "added tests.md (+1 -0)" in diff.text
