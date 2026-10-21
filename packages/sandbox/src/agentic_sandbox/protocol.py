"""The `Sandbox` a run's tools execute in, and the `SandboxManager` that opens one per run.

A sandbox holds a clone of the run's repo at `workdir`, which the sandbox user can read but not
change. Writer nodes get their own git worktree under `worktrees_dir` (`agentic_sandbox.worktree`),
and file contents reach the sandbox through `put_file`. Commands run with `workdir`, or a worktree,
as their current directory. The manager owns the lifecycle: `open()` creates the sandbox and
clones the repo, and leaving the context destroys it, whether the run succeeded, failed or was
cancelled.
"""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from agentic_sandbox.source import RepoSource

# Each stream of an exec is cut to this many bytes; `ExecResult.truncated` says so.
MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_EXEC_TIMEOUT_S = 30.0
# The largest file `put_file` takes.
MAX_PUT_FILE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool = False


class Sandbox(Protocol):
    @property
    def workdir(self) -> str:
        """Where the repo clone lives inside the sandbox."""
        ...

    @property
    def worktrees_dir(self) -> str:
        """The directory writer nodes' worktrees go in, writable by the sandbox user."""
        ...

    async def exec(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
        cwd: str | None = None,
    ) -> ExecResult:
        """Run `argv` (no shell) in `cwd`, by default `workdir`. A command still running after
        `timeout_s` is killed and reported with a non-zero exit code. Raises `ValueError` if
        `cwd` is neither `workdir` nor a directory under `worktrees_dir`."""
        ...

    async def put_file(self, data: bytes) -> str:
        """Store `data` as a new file owned by the sandbox user, outside the clone and its
        worktrees, and return its path in the sandbox; a tool then moves it into place. Raises
        `SandboxError` if `data` is over `MAX_PUT_FILE_BYTES`."""
        ...


class SandboxManager(Protocol):
    def open(self, run_id: UUID, repo: RepoSource) -> AbstractAsyncContextManager[Sandbox]:
        """Create a sandbox for `run_id` holding a shallow clone of `repo`; destroy it on exit.

        Raises `SandboxError` if the sandbox cannot be created or the repo cannot be cloned."""
        ...


def decode_capped(data: bytes) -> tuple[str, bool]:
    """`data` as text, cut to `MAX_OUTPUT_BYTES`; the flag is true when it was cut."""
    truncated = len(data) > MAX_OUTPUT_BYTES
    return data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"), truncated
