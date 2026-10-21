"""A sandbox in a temp directory on the worker, for tests and for `SANDBOX_BACKEND=fake`.

It isolates nothing: commands run on the host with the clone as their current directory. Use it
where Docker is unavailable and the repo is trusted.
"""

import asyncio
import contextlib
import os
import shutil
import stat
import tempfile
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import DEFAULT_EXEC_TIMEOUT_S, ExecResult, decode_capped
from agentic_sandbox.source import RepoSource, clone_shallow


class FakeSandbox:
    """Implements `Sandbox` with local processes."""

    def __init__(self, workdir: Path) -> None:
        self._workdir = workdir

    @property
    def workdir(self) -> str:
        return str(self._workdir)

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = DEFAULT_EXEC_TIMEOUT_S
    ) -> ExecResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self._workdir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return ExecResult(exit_code=127, stdout="", stderr=f"{argv[0]}: {e.strerror}")
        try:
            async with asyncio.timeout(timeout_s):
                out, err = await proc.communicate()
        except TimeoutError:
            return ExecResult(exit_code=124, stdout="", stderr=f"timed out after {timeout_s:g} s")
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        stdout, out_cut = decode_capped(out)
        stderr, err_cut = decode_capped(err)
        assert proc.returncode is not None
        return ExecResult(proc.returncode, stdout, stderr, truncated=out_cut or err_cut)


class FakeSandboxManager:
    """Implements `SandboxManager`: one temp directory per run, removed on exit.

    `local_root` is the only directory local repo paths may come from (none if unset).
    """

    def __init__(self, *, local_root: Path | None = None, base_dir: Path | None = None) -> None:
        self._local_root = local_root
        self._base_dir = base_dir

    @asynccontextmanager
    async def open(self, run_id: UUID, repo: RepoSource) -> AsyncGenerator[FakeSandbox]:
        root = Path(tempfile.mkdtemp(prefix=f"agentic-sandbox-{run_id}-", dir=self._base_dir))
        try:
            await clone_shallow(repo, root / "repo", local_root=self._local_root)
            yield FakeSandbox(root / "repo")
        finally:
            await asyncio.to_thread(shutil.rmtree, root, onexc=_make_writable_and_retry)


def _make_writable_and_retry(func: Callable[[str], object], path: str, exc: BaseException) -> None:
    """git marks its object files read-only, which Windows refuses to delete."""
    if not isinstance(exc, PermissionError):
        raise SandboxError("could not remove the sandbox directory") from exc
    os.chmod(path, stat.S_IWRITE)
    func(path)
