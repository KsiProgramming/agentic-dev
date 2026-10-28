import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_sandbox import (
    MAX_PUT_FILE_BYTES,
    FakeSandboxManager,
    RepoSource,
    SandboxError,
    SandboxManager,
)


def manager(repos: Path, tmp_path: Path) -> FakeSandboxManager:
    base = tmp_path / "sandboxes"
    base.mkdir()
    return FakeSandboxManager(local_root=repos, base_dir=base)


async def test_a_sandbox_holds_the_clone_and_runs_commands_in_it(
    repos: Path, tmp_path: Path
) -> None:
    async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        result = await box.exec([sys.executable, "-c", "import os; print(sorted(os.listdir()))"])

    assert result.exit_code == 0
    assert "README.md" in result.stdout
    assert "src" in result.stdout


async def test_the_sandbox_is_removed_after_use(repos: Path, tmp_path: Path) -> None:
    async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        workdir = Path(box.workdir)
        assert await asyncio.to_thread(workdir.is_dir)

    assert not await asyncio.to_thread(workdir.exists)
    assert list((tmp_path / "sandboxes").iterdir()) == []


async def test_the_sandbox_is_removed_when_the_run_fails(repos: Path, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))):
            raise RuntimeError("boom")

    assert list((tmp_path / "sandboxes").iterdir()) == []


async def test_the_sandbox_is_removed_when_the_run_is_cancelled(
    repos: Path, tmp_path: Path
) -> None:
    opened = asyncio.Event()

    async def use() -> None:
        async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))):
            opened.set()
            await asyncio.sleep(30)

    task = asyncio.create_task(use())
    await opened.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert list((tmp_path / "sandboxes").iterdir()) == []


async def test_a_failed_clone_raises_and_leaves_nothing(repos: Path, tmp_path: Path) -> None:
    with pytest.raises(SandboxError):
        async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "nope"))):
            pytest.fail("the sandbox must not open")

    assert list((tmp_path / "sandboxes").iterdir()) == []


async def test_a_slow_command_times_out(repos: Path, tmp_path: Path) -> None:
    async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        sleep = [sys.executable, "-c", "import time; time.sleep(10)"]
        result = await box.exec(sleep, timeout_s=0.2)

    assert result.exit_code != 0
    assert "timed out" in result.stderr


async def test_an_unknown_command_reports_an_error(repos: Path, tmp_path: Path) -> None:
    async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        result = await box.exec(["no-such-command-xyz"])

    assert result.exit_code == 127


def test_the_fake_manager_implements_the_protocol() -> None:
    _: SandboxManager = FakeSandboxManager()


async def test_a_kept_sandbox_is_reopened_as_it_was(repos: Path, tmp_path: Path) -> None:
    """A run paused at a gate keeps its sandbox; the attempt that continues it gets it back."""
    sandboxes, run_id = manager(repos, tmp_path), uuid4()
    repo = RepoSource(url=str(repos / "hello"))
    async with sandboxes.open(run_id, repo) as box:
        marker = Path(box.worktrees_dir) / "writer.txt"
        await asyncio.to_thread(marker.write_text, "written before the gate")
        sandboxes.keep(run_id)
    assert await asyncio.to_thread(marker.exists)

    async with sandboxes.open(run_id, repo, reuse=True) as box:
        assert Path(box.worktrees_dir) / "writer.txt" == marker
        assert await asyncio.to_thread(marker.read_text) == "written before the gate"

    assert list((tmp_path / "sandboxes").iterdir()) == []


async def test_reuse_without_a_kept_sandbox_creates_a_fresh_one(
    repos: Path, tmp_path: Path
) -> None:
    async with manager(repos, tmp_path).open(
        uuid4(), RepoSource(url=str(repos / "hello")), reuse=True
    ) as box:
        assert (Path(box.workdir) / "README.md").is_file()

    assert list((tmp_path / "sandboxes").iterdir()) == []


async def test_opening_without_reuse_replaces_a_kept_sandbox(repos: Path, tmp_path: Path) -> None:
    """A run resumed after its worker died starts from a fresh clone (phase 1.3)."""
    sandboxes, run_id = manager(repos, tmp_path), uuid4()
    repo = RepoSource(url=str(repos / "hello"))
    async with sandboxes.open(run_id, repo) as box:
        marker = Path(box.worktrees_dir) / "writer.txt"
        await asyncio.to_thread(marker.write_text, "left behind")
        sandboxes.keep(run_id)

    async with sandboxes.open(run_id, repo):
        assert not await asyncio.to_thread(marker.exists)


async def test_artifacts_are_copied_read_only_and_replaced(repos: Path, tmp_path: Path) -> None:
    async with manager(repos, tmp_path).open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        first = await box.put_artifact("notes.md", b"one")
        path = await box.put_artifact("notes.md", b"two")

        assert first == path
        assert Path(path).parent == Path(box.artifacts_dir)
        assert await asyncio.to_thread(Path(path).read_bytes) == b"two"
        with pytest.raises(PermissionError):
            await asyncio.to_thread(Path(path).write_bytes, b"three")
        with pytest.raises(ValueError, match="not an artifact name"):
            await box.put_artifact("../escape.md", b"x")
        with pytest.raises(SandboxError, match="artifact too large"):
            await box.put_artifact("big.txt", b"x" * (MAX_PUT_FILE_BYTES + 1))
