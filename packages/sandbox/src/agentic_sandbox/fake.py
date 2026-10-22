"""A sandbox in a temp directory on the worker, for tests and for `SANDBOX_BACKEND=fake`.

It isolates nothing: commands run on the host with the clone as their current directory. Use it
where Docker is unavailable and the repo is trusted. The temp directory has the layout of the
Docker sandbox's `/workspace`: `repo/` (the clone), `worktrees/` and `.incoming/`. Like the
sandbox image, commands read no system or user git config.
"""

import asyncio
import contextlib
import os
import shutil
import stat
import tempfile
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import (
    DEFAULT_EXEC_TIMEOUT_S,
    MAX_PUT_FILE_BYTES,
    MAX_TAKE_FILE_BYTES,
    ExecResult,
    decode_capped,
)
from agentic_sandbox.source import RepoSource, clone_shallow

_GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


class FakeSandbox:
    """Implements `Sandbox` with local processes. `root` holds the clone at `root/repo`."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._workdir = root / "repo"

    @property
    def workdir(self) -> str:
        return str(self._workdir)

    @property
    def worktrees_dir(self) -> str:
        return str(self._root / "worktrees")

    async def exec(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
        cwd: str | None = None,
    ) -> ExecResult:
        workdir = self._checked_cwd(cwd)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=workdir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **_GIT_ENV},
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

    async def put_file(self, data: bytes) -> str:
        if len(data) > MAX_PUT_FILE_BYTES:
            raise SandboxError(f"file too large for the sandbox: {len(data)} bytes")
        path = self._root / ".incoming" / uuid4().hex
        await asyncio.to_thread(path.write_bytes, data)
        return path.as_posix()

    @property
    def staging_dir(self) -> str:
        return (self._root / ".incoming").as_posix()

    async def take_file(self, path: str) -> bytes:
        return await asyncio.to_thread(self._take_file, Path(path))

    def _take_file(self, file: Path) -> bytes:
        if file.parent.resolve() != (self._root / ".incoming").resolve() or file.is_symlink():
            raise ValueError("only files directly in the staging directory can be taken")
        try:
            size = file.stat().st_size
            if size > MAX_TAKE_FILE_BYTES:
                raise SandboxError(f"file too large to take from the sandbox: {size} bytes")
            return file.read_bytes()
        except OSError:
            raise SandboxError("no such file in the sandbox") from None
        finally:
            file.unlink(missing_ok=True)

    def _checked_cwd(self, cwd: str | None) -> Path:
        """`cwd` (default the clone) if it is the clone or a directory under the worktrees."""
        if cwd is None:
            return self._workdir
        path = Path(cwd).resolve()
        worktrees = (self._root / "worktrees").resolve()
        in_worktree = path != worktrees and path.is_relative_to(worktrees)
        if in_worktree or path == self._workdir.resolve():
            return path
        raise ValueError("cwd must be the repo checkout or a worktree")


class FakeSandboxManager:
    """Implements `SandboxManager`: one directory per run, `agentic-sandbox-<run-id>` under
    `base_dir` (default: the system temp directory), removed on exit unless kept.

    `local_root` is the only directory local repo paths may come from (none if unset).
    """

    def __init__(self, *, local_root: Path | None = None, base_dir: Path | None = None) -> None:
        self._local_root = local_root
        self._base_dir = base_dir or Path(tempfile.gettempdir())
        self._kept: set[UUID] = set()

    def keep(self, run_id: UUID) -> None:
        self._kept.add(run_id)

    @asynccontextmanager
    async def open(
        self,
        run_id: UUID,
        repo: RepoSource,
        *,
        reuse: bool = False,
        git_env: Mapping[str, str] | None = None,
    ) -> AsyncGenerator[FakeSandbox]:
        root = self._base_dir / f"agentic-sandbox-{run_id}"
        self._kept.discard(run_id)
        try:
            if not (reuse and await asyncio.to_thread((root / "repo").is_dir)):
                await asyncio.to_thread(_remove_dir, root)
                await asyncio.to_thread(root.mkdir, parents=True)
                await clone_shallow(
                    repo, root / "repo", local_root=self._local_root, git_env=git_env
                )
                (root / "worktrees").mkdir()
                (root / ".incoming").mkdir()
            yield FakeSandbox(root)
        finally:
            if run_id in self._kept:
                self._kept.discard(run_id)
            else:
                await asyncio.to_thread(_remove_dir, root)


def _remove_dir(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root, onexc=_make_writable_and_retry)


def _make_writable_and_retry(func: Callable[[str], object], path: str, exc: BaseException) -> None:
    """git marks its object files read-only, which Windows refuses to delete."""
    if not isinstance(exc, PermissionError):
        raise SandboxError("could not remove the sandbox directory") from exc
    os.chmod(path, stat.S_IWRITE)
    func(path)
