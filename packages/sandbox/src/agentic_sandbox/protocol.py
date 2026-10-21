"""The `Sandbox` a run's tools execute in, and the `SandboxManager` that opens one per run.

A sandbox holds a clone of the run's repo at `workdir`. Commands run with `workdir` as their
current directory. The manager owns the lifecycle: `open()` creates the sandbox and clones the
repo, and leaving the context destroys it, whether the run succeeded, failed or was cancelled.
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

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = DEFAULT_EXEC_TIMEOUT_S
    ) -> ExecResult:
        """Run `argv` (no shell) in `workdir`. A command still running after `timeout_s` is
        killed and reported with a non-zero exit code."""
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
