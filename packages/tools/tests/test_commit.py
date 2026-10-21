"""`commit` on a writer's `repo` server, on both sandbox backends (see conftest)."""

import re
from uuid import UUID

from agentic_sandbox import Sandbox, Worktree
from agentic_tools.repo import COMMIT_AUTHOR, RepoLimits
from agentic_tools.testing import CallRepo

HOOK = "#!/bin/sh\ntouch hooked\n"


async def sh(box: Sandbox, script: str) -> tuple[int, str]:
    result = await box.exec(["sh", "-c", script])
    return result.exit_code, (result.stdout + result.stderr).strip()


async def test_commits_on_the_writer_branch_as_the_platform(
    call_writer: CallRepo, worktree: Worktree, run_id: UUID
) -> None:
    await call_writer("write_file", path="NOTES.md", content="hi\n")

    is_error, text = await call_writer("commit", message="Add NOTES.md")

    assert not is_error
    assert re.fullmatch(rf"[0-9a-f]{{7,}} on agent/{run_id}/writer: NOTES\.md", text)
    name, email = COMMIT_AUTHOR
    assert await sh(worktree, "git log -1 --format='%an <%ae>|%cn <%ce>|%s'") == (
        0,
        f"{name} <{email}>|{name} <{email}>|Add NOTES.md",
    )
    assert await sh(worktree, "git log --format=%s") == (0, "Add NOTES.md\ninit")
    assert await sh(worktree, "git status --porcelain") == (0, "")


async def test_the_result_lists_every_changed_file(call_writer: CallRepo) -> None:
    for name in ("a.txt", "b/c.txt", "README.md"):
        await call_writer("write_file", path=name, content="x\n")

    _, text = await call_writer("commit", message="three")

    assert text.split(": ", 1)[1] == "README.md, a.txt, b/c.txt"


async def test_many_changed_files_are_counted_not_listed(call_writer: CallRepo) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        await call_writer("write_file", path=name, content="x\n")

    _, text = await call_writer("commit", RepoLimits(max_commit_paths=2), message="three")

    assert text.endswith(": a.txt, b.txt (and 1 more)")


async def test_nothing_to_commit_is_an_error(call_writer: CallRepo) -> None:
    assert await call_writer("commit", message="empty") == (
        True,
        "Error executing tool commit: nothing to commit: write a file first",
    )


async def test_a_blank_message_is_refused(call_writer: CallRepo) -> None:
    await call_writer("write_file", path="x.txt", content="x\n")

    is_error, text = await call_writer("commit", message="  \n ")

    assert is_error
    assert "must not be blank" in text


async def test_the_message_is_data_not_shell(call_writer: CallRepo, worktree: Worktree) -> None:
    message = "$(touch pwned) `touch pwned2`; touch pwned3"
    await call_writer("write_file", path="x.txt", content="x\n")

    assert not (await call_writer("commit", message=message))[0]

    assert await sh(worktree, "git log -1 --format=%s") == (0, message)
    assert await sh(worktree, "ls pwned* 2>/dev/null; true") == (0, "")


async def test_the_repos_hooks_never_run(
    call_writer: CallRepo, sandbox: Sandbox, worktree: Worktree
) -> None:
    # The clone's .git is shared by every worktree: plant hooks there, and point the repo's own
    # config at a second hooks directory.
    plant = (
        "for d in .git/hooks .git/more-hooks; do mkdir -p $d; "
        f"for h in pre-commit commit-msg post-commit; do printf '{HOOK}' > $d/$h; chmod +x $d/$h; "
        "done; done; git -c safe.directory=* config core.hooksPath .git/more-hooks"
    )
    assert (await sh(sandbox, plant))[0] == 0
    await call_writer("write_file", path="x.txt", content="x\n")

    assert not (await call_writer("commit", message="hooked?"))[0]

    assert (await sh(worktree, "test -e hooked"))[0] == 1
    assert (await sh(sandbox, "test -e hooked"))[0] == 1
