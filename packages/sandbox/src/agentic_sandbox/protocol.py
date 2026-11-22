"""The `Sandbox` a run's tools execute in, and the `SandboxManager` that opens one per run.

A sandbox holds a clone of the run's repo at `workdir`, which the sandbox user can read but not
change. Writer nodes get their own git worktree under `worktrees_dir` (`agentic_sandbox.worktree`),
and file contents reach the sandbox through `put_file` (and leave it through `take_file`, e.g. a
writer's branch as a git bundle). The run's artifacts are copied to `artifacts_dir`
(`put_artifact`), where the sandbox user can read them but not change them. Commands run with
`workdir`, or a worktree, as their current directory. Heavier work (a .NET restore and build,
4.8) runs as a job (`run_job`): a short-lived container on the sandbox's files with its own
limits, working in a directory under `staging_dir`, never in the checkout. The manager owns the
lifecycle: `open()`
creates the sandbox and clones the repo, and leaving the context destroys it, whether the run
succeeded, failed or was cancelled, unless the run kept it (`keep()`). A run that pauses at a gate
keeps its sandbox, and the attempt that continues it opens it again (`open(..., reuse=True)`); a
run that fails or is cancelled keeps it for a time to live (12.3), after which a sweep removes
it (`discard()`). A fresh sandbox for a run
that has already worked is cloned at the run's base commit and gets the writers' branches the run
saved back (`open(..., at=..., restore=...)`, 12.2).
"""

import re
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol
from uuid import UUID

from agentic_sandbox.source import RepoSource

if TYPE_CHECKING:
    from agentic_sandbox.bundle import BranchBundle

# Each stream of an exec is cut to this many bytes; `ExecResult.truncated` says so.
MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_EXEC_TIMEOUT_S = 30.0
# The largest file `put_file` takes.
MAX_PUT_FILE_BYTES = 1024 * 1024
# The largest file `take_file` hands out (a writer's branch, bundled).
MAX_TAKE_FILE_BYTES = 64 * 1024 * 1024


ARTIFACT_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,58}\.(json|md|txt)$")
"""A run artifact's name, as the workflow spec allows it (`agentic_engine.spec.ArtifactName`)."""


def check_artifact_name(name: str) -> None:
    """Raises `ValueError` unless `name` is a run artifact's name, so it is one file name."""
    if not ARTIFACT_NAME.match(name):
        raise ValueError(f"not an artifact name: {name!r}")


type JobNetwork = Literal["none", "nuget", "npm", "pypi"]
"""Where a job container may connect: nowhere, or one package registry only, through that
registry's own egress proxy on its own internal network (4.8, 13.2)."""


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

    @property
    def restored(self) -> tuple[str, ...]:
        """The branches `open` fetched into this sandbox from saved bundles (12.2): empty for a
        sandbox reopened as it was kept, or for a run with nothing saved."""
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

    @property
    def staging_dir(self) -> str:
        """Where staged files live: writable by the sandbox user, outside the clone and its
        worktrees. Commands may write a file here for `take_file` to hand out."""
        ...

    async def take_file(self, path: str) -> bytes:
        """The bytes of the file `path`, directly in `staging_dir`, which is then removed.
        Raises `ValueError` for any other path, and `SandboxError` if the file is missing or over
        `MAX_TAKE_FILE_BYTES`."""
        ...

    @property
    def artifacts_dir(self) -> str:
        """Where the run's artifacts are copied: readable by the sandbox user, not writable."""
        ...

    async def put_artifact(self, name: str, data: bytes) -> str:
        """Copy the run artifact `name` to `artifacts_dir`, replacing an older version, and
        return its path. Raises `ValueError` if `name` is not an artifact's name, and
        `SandboxError` if `data` is over `MAX_PUT_FILE_BYTES` or cannot be copied."""
        ...

    @property
    def job_networks(self) -> frozenset[JobNetwork]:
        """The networks `run_job` can give a job: `none`, and each registry (`nuget`, `npm`,
        `pypi`) the deployment has an egress proxy for. Empty when the sandbox runs no jobs."""
        ...

    async def run_job(
        self,
        argv: Sequence[str],
        *,
        network: JobNetwork,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        """Run `argv` (no shell) in a short-lived job container (4.8): the sandbox's image and
        files, with its own, larger limits, on `network`, as the sandbox user. `cwd` is a
        directory under `staging_dir`, where the job works (a job never changes the checkout).
        The container is removed when the job ends, whatever its outcome; a job still running
        after `timeout_s` is stopped and reported with exit code 124. Raises `ValueError` for any
        other `cwd`, and `SandboxError` if `network` is not in `job_networks` or the container
        cannot be run."""
        ...


class SandboxManager(Protocol):
    def open(
        self,
        run_id: UUID,
        repo: RepoSource,
        *,
        reuse: bool = False,
        git_env: Mapping[str, str] | None = None,
        at: str | None = None,
        restore: Sequence["BranchBundle"] = (),
    ) -> AbstractAsyncContextManager[Sandbox]:
        """Create a sandbox for `run_id` holding a shallow clone of `repo`; destroy it on exit,
        unless `keep(run_id)` was called meanwhile.

        Without `reuse`, a sandbox the run already has (left by an attempt that died) is replaced
        by a fresh one. With `reuse`, the one it kept is opened again as it was, with its writers'
        worktrees and commits; if there is none, a fresh one is created. `git_env` goes to the
        clone (`clone_shallow`), e.g. to authenticate to a private repo; the sandbox never sees
        it.

        A fresh sandbox is cloned at the commit `at` when it is given (the run's base, 12.2), and
        each bundle in `restore` is fetched into it as its branch (`import_bundles`), which
        `Sandbox.restored` then names. A reopened sandbox is left as it was kept.

        Raises `SandboxError` if the sandbox cannot be created or the repo cannot be cloned."""
        ...

    def keep(self, run_id: UUID) -> None:
        """Leave the run's open sandbox in place when its context exits (a run paused at a
        gate), so a later `open(..., reuse=True)` gets it back."""
        ...

    async def discard(self, run_id: UUID) -> None:
        """Remove the sandbox the run kept, if any: a kept sandbox past its time to live (12.3)."""
        ...

    async def exists(self, run_id: UUID) -> bool:
        """Whether a sandbox of the run is left on this host, kept or not (12.3: a run ended while
        paused at a gate keeps the sandbox it kept there)."""
        ...


def decode_capped(data: bytes) -> tuple[str, bool]:
    """`data` as text, cut to `MAX_OUTPUT_BYTES`; the flag is true when it was cut."""
    truncated = len(data) > MAX_OUTPUT_BYTES
    return data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"), truncated
