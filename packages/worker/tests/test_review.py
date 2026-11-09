"""A gate's review of a run's writer branches in its sandbox (phase 3.6)."""

import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest

from agentic_engine.gate import (
    MAX_REVIEW_FILE_BYTES,
    MAX_REVIEW_FILES,
    FileEdit,
    GateReviewError,
)
from agentic_sandbox import FakeSandboxManager, RepoSource, Sandbox, Worktree, add_worktree
from agentic_sandbox.testing import make_repo
from agentic_worker.review import SandboxGateReview

RUN_ID = UUID("00000000-0000-4000-8000-000000000003")
_COMMIT = "git add -A && git -c user.name=t -c user.email=t@e.invalid -c commit.gpgsign=false"

pytestmark = pytest.mark.skipif(
    not (shutil.which("sh") and shutil.which("git")), reason="needs sh and git on the host"
)


@pytest.fixture
async def sandbox(tmp_path: Path) -> AsyncIterator[Sandbox]:
    make_repo(tmp_path / "repos" / "hello", {"README.md": "# Hello\n", "keep.md": "keep\n"})
    manager = FakeSandboxManager(local_root=tmp_path / "repos")
    async with manager.open(RUN_ID, RepoSource(url=str(tmp_path / "repos" / "hello"))) as box:
        yield box


async def write(sandbox: Sandbox, node_id: str, script: str) -> Worktree:
    tree = await add_worktree(sandbox, RUN_ID, node_id)
    result = await tree.exec(["sh", "-c", f"{script} && {_COMMIT} commit -q -m work"])
    assert result.exit_code == 0, result.stderr
    return tree


async def test_editable_files_come_with_both_sides(sandbox: Sandbox) -> None:
    await write(
        sandbox,
        "writer",
        "printf '# Hello, edited\\n' > README.md && mkdir docs && printf '# A\\n' > docs/a.md"
        " && printf 'a\\0b' > logo.bin && rm keep.md",
    )
    review = SandboxGateReview(sandbox, RUN_ID, {"writer"})

    changes = await review.changes(["writer", "approve"])

    by_path = {c.path: c for c in changes}
    assert by_path["README.md"].model_dump(exclude={"node_id", "path"}) == {
        "old_path": None,
        "status": "modified",
        "editable": True,
        "reason": None,
        "before": "# Hello\n",
        "after": "# Hello, edited\n",
    }
    assert (by_path["docs/a.md"].editable, by_path["docs/a.md"].before) == (True, None)
    assert by_path["docs/a.md"].after == "# A\n"
    assert (by_path["logo.bin"].reason, by_path["logo.bin"].after) == ("binary", None)
    assert (by_path["keep.md"].reason, by_path["keep.md"].before) == ("deleted", None)
    assert {c.node_id for c in changes} == {"writer"}


async def test_only_writers_that_ran_are_shown(sandbox: Sandbox) -> None:
    await write(sandbox, "first", "printf 'x\\n' > one.md")
    await write(sandbox, "second", "printf 'y\\n' > two.md")
    review = SandboxGateReview(sandbox, RUN_ID, {"first", "second", "never"})

    changes = await review.changes(["first", "never"])

    assert [(c.node_id, c.path) for c in changes] == [("first", "one.md")]


async def test_large_files_and_files_past_the_caps_are_listed_without_contents(
    sandbox: Sandbox,
) -> None:
    count = MAX_REVIEW_FILES + 1
    await write(
        sandbox,
        "writer",
        f"head -c {MAX_REVIEW_FILE_BYTES + 1} /dev/zero | tr '\\0' 'x' > big.txt"
        f" && i=0 && while [ $i -lt {count} ]; do printf 'p\\n' > p$i.md; i=$((i+1)); done",
    )
    review = SandboxGateReview(sandbox, RUN_ID, {"writer"})

    changes = await review.changes(["writer"])

    big = next(c for c in changes if c.path == "big.txt")
    assert (big.editable, big.reason, big.after) == (False, "too_large", None)
    pages = [c for c in changes if c.path.startswith("p")]
    assert len(pages) == count
    assert sum(c.editable for c in pages) == MAX_REVIEW_FILES
    assert [c.reason for c in pages if not c.editable] == ["over_limit"]


async def test_apply_commits_the_edits_on_the_writer_branch(sandbox: Sandbox) -> None:
    tree = await write(sandbox, "writer", "printf '# A\\n' > a.md")
    review = SandboxGateReview(sandbox, RUN_ID, {"writer"})
    edit = FileEdit(node_id="writer", path="a.md", content="# A, reviewed\n")

    commits = await review.apply("approve", [edit])

    tip = (await tree.exec(["git", "rev-parse", "HEAD"])).stdout.strip()
    assert commits == {"writer": tip}
    message = (await tree.exec(["git", "log", "-1", "--format=%B"])).stdout.strip()
    assert message == "Edit at gate approve\n\nEdited-by: reviewer"
    assert (await review.changes(["writer"]))[0].after == "# A, reviewed\n"
    assert await review.apply("approve", [edit]) == commits  # nothing new to commit


async def test_apply_refuses_a_node_that_is_not_a_writer(sandbox: Sandbox) -> None:
    review = SandboxGateReview(sandbox, RUN_ID, {"writer"})

    with pytest.raises(GateReviewError, match="not a writer"):
        await review.apply("approve", [FileEdit(node_id="other", path="a.md", content="x")])


async def test_a_gate_shows_and_edits_each_task_of_an_orchestrator(sandbox: Sandbox) -> None:
    """6.1: an orchestrator's task writers (`fix.t1`) are shown and edited on their branches;
    a task of an orchestrator whose workers do not write is not."""
    await write(sandbox, "fix.t1", "printf 'one\n' > one.md")
    await write(sandbox, "fix.t2", "printf 'two\n' > two.md")
    review = SandboxGateReview(sandbox, RUN_ID, set(), {"fix"})

    changes = await review.changes(["fix", "fix.t1", "fix.t2", "other.t1"])
    commits = await review.apply(
        "approve", [FileEdit(node_id="fix.t2", path="two.md", content="2\n")]
    )

    assert [(c.node_id, c.path) for c in changes] == [("fix.t1", "one.md"), ("fix.t2", "two.md")]
    assert list(commits) == ["fix.t2"]
    with pytest.raises(GateReviewError, match="not a writer"):
        await review.apply("approve", [FileEdit(node_id="other.t1", path="x.md", content="x")])
