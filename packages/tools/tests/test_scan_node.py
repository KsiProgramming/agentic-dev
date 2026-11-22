"""`scan.lint {node}` (13.3): the linters run on a writer's committed tree, with 13.1's refusals."""

import re
from typing import Any
from uuid import UUID

from mcp import Client

from agentic_runtime import ReadableWriter, ReadableWriters
from agentic_sandbox import Sandbox, add_worktree, branch_name
from agentic_tools.scan import build_scan_server

_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"


def readable(run_id: UUID, *completed: str, known: tuple[str, ...]) -> ReadableWriters:
    writers = ReadableWriters(lambda node: branch_name(run_id, node))
    writers.set([ReadableWriter(n, "writer") for n in completed], known=known)
    return writers


async def lint(
    sandbox: Sandbox, state: ReadableWriters | None, **arguments: str
) -> tuple[bool, str, dict[str, Any]]:
    async with Client(build_scan_server(sandbox, readable=state)) as client:  # type: ignore[arg-type]
        result = await client.call_tool("lint", {"linters": ["ruff"], **arguments})
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return (
        result.is_error,
        re.sub(r"^Error executing tool \w+: ", "", text),
        result.structured_content or {},
    )


async def test_lint_with_node_reads_the_writers_branch_not_the_checkout(
    sandbox: Sandbox, run_id: UUID
) -> None:
    tree = await add_worktree(sandbox, run_id, "writer")
    script = (
        "printf '[lint]\\nselect = [\"F\"]\\n' > ruff.toml && printf 'import os\\n' > src/bad.py"
        f" && {_COMMIT} commit -q -m x"
    )
    done = await tree.exec(["sh", "-c", script])
    assert done.exit_code == 0, done.stderr
    state = readable(run_id, "writer", known=("writer",))

    is_error, text, on_branch = await lint(sandbox, state, node="writer")

    assert not is_error, text
    assert [f["path"] for f in on_branch["findings"]] == ["src/bad.py"]
    # The extracted tree is gone afterwards.
    left = await sandbox.exec(["sh", "-c", f"ls {sandbox.staging_dir}"])
    assert "tree-" not in left.stdout


async def test_lint_with_node_gives_the_three_refusals(sandbox: Sandbox, run_id: UUID) -> None:
    await add_worktree(sandbox, run_id, "empty")
    state = readable(run_id, "empty", known=("empty", "late"))

    refused = {n: (await lint(sandbox, state, node=n))[1] for n in ("nobody", "late", "empty")}

    assert refused == {
        "nobody": "'nobody' is not a writer of this run",
        "late": "writer 'late' has not run before this step",
        "empty": "writer 'empty' has no commits",
    }
