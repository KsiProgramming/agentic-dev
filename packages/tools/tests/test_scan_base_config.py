"""`scan.lint {node, config: "base"}` (13.5): a writer's work is linted by the analyzer config the
run started with, so a change that relaxes a rule is still judged by it."""

import re
from typing import Any
from uuid import UUID

from mcp import Client

from agentic_runtime import ReadableWriter, ReadableWriters
from agentic_sandbox import Sandbox, add_worktree, branch_name
from agentic_tools.scan import build_scan_server

_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"


def readable(run_id: UUID) -> ReadableWriters:
    writers = ReadableWriters(lambda node: branch_name(run_id, node))
    writers.set([ReadableWriter("writer", "writer")], known=("writer",))
    return writers


async def lint(
    sandbox: Sandbox, state: ReadableWriters, **arguments: Any
) -> tuple[bool, str, dict[str, Any]]:
    async with Client(build_scan_server(sandbox, readable=state)) as client:  # type: ignore[arg-type]
        result = await client.call_tool("lint", {"linters": ["ruff"], **arguments})
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return (
        result.is_error,
        re.sub(r"^Error executing tool \w+: ", "", text),
        result.structured_content or {},
    )


async def writer_commits(sandbox: Sandbox, run_id: UUID, script: str) -> None:
    tree = await add_worktree(sandbox, run_id, "writer")
    done = await tree.exec(["sh", "-c", f"{script} && {_COMMIT} commit -q -m work"])
    assert done.exit_code == 0, done.stderr


async def base_has_ruff_config(sandbox: Sandbox, config: str, name: str = "ruff.toml") -> None:
    """The run's base: a ruff config of its own, committed on the checkout's `HEAD`."""
    script = f"printf '{config}' > {name} && {_COMMIT} commit -q -m base-config"
    done = await sandbox.exec(
        ["sh", "-c", f'git -c safe.directory="$(pwd -P)" -C . status >/dev/null; {script}']
    )
    assert done.exit_code == 0, done.stderr


async def test_a_change_that_turns_off_a_rule_is_still_judged_by_the_base_config(
    sandbox: Sandbox, run_id: UUID
) -> None:
    await base_has_ruff_config(sandbox, '[lint]\\nselect = ["F"]\\n')
    # The writer adds an unused import and turns the rule off in the config.
    await writer_commits(
        sandbox,
        run_id,
        "printf 'import os\\n' > src/bad.py && printf '[lint]\\nselect = [\"E\"]\\n' > ruff.toml",
    )
    state = readable(run_id)

    own = (await lint(sandbox, state, node="writer"))[2]
    base = (await lint(sandbox, state, node="writer", config="base"))[2]

    assert [f["path"] for f in own["findings"]] == []  # the writer's own config hides it
    assert [f["path"] for f in base["findings"]] == ["src/bad.py"]


async def test_a_config_file_the_writer_added_is_not_used_and_one_it_removed_is_back(
    sandbox: Sandbox, run_id: UUID
) -> None:
    await base_has_ruff_config(sandbox, '[lint]\\nselect = ["F"]\\n')
    await writer_commits(
        sandbox,
        run_id,
        "printf 'import os\\n' > src/bad.py && rm ruff.toml"
        " && mkdir -p src && printf '[lint]\\nignore = [\"F\"]\\n' > src/ruff.toml",
    )
    state = readable(run_id)

    base = (await lint(sandbox, state, node="writer", config="base"))[2]

    assert [f["path"] for f in base["findings"]] == ["src/bad.py"]


async def test_a_pyprojects_tool_ruff_table_is_the_bases(sandbox: Sandbox, run_id: UUID) -> None:
    await base_has_ruff_config(
        sandbox,
        '[project]\\nname = "x"\\nversion = "0"\\n\\n[tool.ruff.lint]\\nselect = ["F"]\\n',
        "pyproject.toml",
    )
    await writer_commits(
        sandbox,
        run_id,
        "printf 'import os\\n' > src/bad.py"
        ' && printf \'[project]\\nname = "x"\\nversion = "0"\\n\\n'
        '[tool.ruff.lint]\\nignore = ["F"]\\n\' > pyproject.toml',
    )
    state = readable(run_id)

    own = (await lint(sandbox, state, node="writer"))[2]
    base = (await lint(sandbox, state, node="writer", config="base"))[2]

    assert own["findings"] == []
    assert [f["path"] for f in base["findings"]] == ["src/bad.py"]


async def test_the_checkout_and_the_writers_worktree_are_unchanged_and_the_tree_is_removed(
    sandbox: Sandbox, run_id: UUID
) -> None:
    await base_has_ruff_config(sandbox, '[lint]\\nselect = ["F"]\\n')
    await writer_commits(sandbox, run_id, "printf '[lint]\\nselect = [\"E\"]\\n' > ruff.toml")
    state = readable(run_id)
    before = (await sandbox.exec(["sh", "-c", "cat ruff.toml"])).stdout

    await lint(sandbox, state, node="writer", config="base")

    assert (await sandbox.exec(["sh", "-c", "cat ruff.toml"])).stdout == before
    tree = await add_worktree(sandbox, run_id, "writer")
    kept = await tree.exec(["sh", "-c", "cat ruff.toml"])
    assert 'select = ["E"]' in kept.stdout  # the writer's own file is still its own
    left = await sandbox.exec(["sh", "-c", f"ls {sandbox.staging_dir}"])
    assert "config-" not in left.stdout


async def test_config_needs_a_node(sandbox: Sandbox, run_id: UUID) -> None:
    is_error, text, _ = await lint(sandbox, readable(run_id), config="base")

    assert is_error
    assert "`config` needs `node`" in text
