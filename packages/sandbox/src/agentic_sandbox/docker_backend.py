"""Sandboxes as local Docker containers, one per run.

The repo is cloned on the worker and copied into a per-run volume mounted at `/workspace`. The
container has no network, a read-only root filesystem, no capabilities and runs as a non-root
user. The checkout at `/workspace/repo` is owned by root, so agents can read it but not change
it. Its `.git`, `/workspace/worktrees` (writer nodes' worktrees) and `/workspace/.incoming` (files
on their way in) belong to the sandbox user, so writers can commit on their own branch. Every
container and volume carries the `agentic.run_id` label, so leftovers can be swept. A run that is
resumed after its worker died gets a fresh sandbox: `open` first removes the one it left.

docker-py is blocking, so its calls run in threads.
"""

import asyncio
import io
import logging
import math
import posixpath
import shutil
import tarfile
import tempfile
import time
from collections.abc import AsyncGenerator, Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.models.volumes import Volume
from docker.types import Mount

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import (
    DEFAULT_EXEC_TIMEOUT_S,
    MAX_PUT_FILE_BYTES,
    ExecResult,
    decode_capped,
)
from agentic_sandbox.source import RepoSource, clone_shallow

log = logging.getLogger("agentic_sandbox")

# Built from `packages/sandbox/Dockerfile` (compose builds it); other images are pulled if missing.
DEFAULT_IMAGE = "agentic-dev/sandbox:dev"
SANDBOX_DOCKERFILE_DIR = "packages/sandbox"
RUN_LABEL = "agentic.run_id"
WORKSPACE = "/workspace"
REPO_DIR = f"{WORKSPACE}/repo"
WORKTREES_DIR = f"{WORKSPACE}/worktrees"
INCOMING_DIR = f"{WORKSPACE}/.incoming"
SANDBOX_UID = 1000
SANDBOX_USER = f"{SANDBOX_UID}:{SANDBOX_UID}"
# Exit codes `timeout` gives a command it had to stop: GNU's, and busybox's (SIGTERM).
TIMED_OUT = 124
_TIMED_OUT_CODES = {TIMED_OUT, 128 + 15}


@dataclass(frozen=True)
class SandboxLimits:
    memory: str = "512m"
    cpus: float = 1.0
    pids: int = 256


class DockerSandbox:
    """Implements `Sandbox` with `docker exec` in the run's container."""

    def __init__(self, container: Container) -> None:
        self._container = container

    @property
    def workdir(self) -> str:
        return REPO_DIR

    @property
    def worktrees_dir(self) -> str:
        return WORKTREES_DIR

    async def exec(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
        cwd: str | None = None,
    ) -> ExecResult:
        workdir = _checked_cwd(cwd)
        # The container stops the command itself; the thread only waits for it.
        cmd = ["timeout", str(max(1, math.ceil(timeout_s))), *argv]
        try:
            exit_code, out, err = await asyncio.to_thread(self._exec, cmd, workdir)
        except DockerException as e:
            log.warning("sandbox exec failed: %s", e)
            raise SandboxError("the sandbox is not available") from e
        stdout, out_cut = decode_capped(out)
        stderr, err_cut = decode_capped(err)
        if exit_code in _TIMED_OUT_CODES:
            exit_code = TIMED_OUT
            stderr += f"\ntimed out after {timeout_s:g} s"
        return ExecResult(exit_code, stdout, stderr, truncated=out_cut or err_cut)

    def _exec(self, cmd: list[str], workdir: str) -> tuple[int, bytes, bytes]:
        result = self._container.exec_run(cmd, user=SANDBOX_USER, workdir=workdir, demux=True)
        # With `demux=True` the output is a `(stdout, stderr)` pair, each `None` when empty.
        out, err = cast(tuple[bytes | None, bytes | None], result.output)
        return result.exit_code or 0, out or b"", err or b""

    async def put_file(self, data: bytes) -> str:
        if len(data) > MAX_PUT_FILE_BYTES:
            raise SandboxError(f"file too large for the sandbox: {len(data)} bytes")
        name = uuid4().hex
        archive = _one_file_tar(name, data)
        try:
            copied = await asyncio.to_thread(_put_archive, self._container, archive, INCOMING_DIR)
        except DockerException as e:
            log.warning("sandbox put_file failed: %s", e)
            raise SandboxError("the sandbox is not available") from e
        if not copied:
            raise SandboxError("could not copy the file into the sandbox")
        return f"{INCOMING_DIR}/{name}"


def _checked_cwd(cwd: str | None) -> str:
    """`cwd` (default the checkout) if it is the checkout or a directory under the worktrees."""
    if cwd is None:
        return REPO_DIR
    if posixpath.normpath(cwd) == cwd and (cwd == REPO_DIR or cwd.startswith(f"{WORKTREES_DIR}/")):
        return cwd
    raise ValueError("cwd must be the repo checkout or a worktree")


class DockerSandboxManager:
    """Implements `SandboxManager` with one container and one volume per run.

    `client` defaults to `docker.from_env()`. `local_root` is the only directory local repo paths
    may come from (none if unset).
    """

    def __init__(
        self,
        client: docker.DockerClient | None = None,
        *,
        image: str = DEFAULT_IMAGE,
        limits: SandboxLimits | None = None,
        local_root: Path | None = None,
    ) -> None:
        self._client = client or docker.from_env()
        self._image = image
        self._limits = limits or SandboxLimits()
        self._local_root = local_root

    @asynccontextmanager
    async def open(self, run_id: UUID, repo: RepoSource) -> AsyncGenerator[DockerSandbox]:
        name = f"agentic-sandbox-{run_id}"
        started = time.monotonic()
        volume: Volume | None = None
        container: Container | None = None
        try:
            archive = await self._clone(repo)
            try:
                if leftovers := await asyncio.to_thread(
                    _sweep, self._client, f"{RUN_LABEL}={run_id}"
                ):
                    log.info("sandbox %s: removed %d left by an earlier attempt", name, leftovers)
                volume = await asyncio.to_thread(
                    self._client.volumes.create, name=name, labels={RUN_LABEL: str(run_id)}
                )
                container = await asyncio.to_thread(self._create, name, run_id)
                if not await asyncio.to_thread(_put_archive, container, archive, WORKSPACE):
                    raise SandboxError("could not copy the repo into the sandbox")
                await asyncio.to_thread(container.start)
            except DockerException as e:
                log.warning("sandbox %s could not be created: %s", name, e)
                raise SandboxError("could not create the sandbox container") from e
            log.info("sandbox %s ready in %.2f s", name, time.monotonic() - started)
            yield DockerSandbox(container)
        finally:
            if container is not None or volume is not None:
                await asyncio.to_thread(_remove, container, volume)
                log.info("sandbox %s removed after %.2f s", name, time.monotonic() - started)

    async def _clone(self, repo: RepoSource) -> bytes:
        """A tar of the sandbox's `/workspace`: a shallow clone of `repo` at `repo/`, and the
        empty `worktrees/` and `.incoming/`."""
        staging = Path(tempfile.mkdtemp(prefix="agentic-clone-"))
        try:
            await clone_shallow(repo, staging / "repo", local_root=self._local_root)
            return await asyncio.to_thread(_workspace_tar, staging / "repo")
        finally:
            await asyncio.to_thread(shutil.rmtree, staging, ignore_errors=True)

    def _create(self, name: str, run_id: UUID) -> Container:
        def create() -> Container:
            return self._client.containers.create(
                self._image,
                command=["tail", "-f", "/dev/null"],
                name=name,
                labels={RUN_LABEL: str(run_id)},
                user=SANDBOX_USER,
                working_dir=WORKSPACE,
                network_mode="none",
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                mounts=[Mount(WORKSPACE, name, type="volume")],
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                mem_limit=self._limits.memory,
                nano_cpus=int(self._limits.cpus * 1e9),
                pids_limit=self._limits.pids,
                init=True,
            )

        try:
            return create()
        except ImageNotFound:
            log.info("pulling sandbox image %s", self._image)
            try:
                self._client.images.pull(self._image)
            except DockerException as e:
                raise SandboxError(
                    f"sandbox image {self._image} is not available; build it with "
                    f"`docker build -t {self._image} {SANDBOX_DOCKERFILE_DIR}`"
                ) from e
            return create()


def _put_archive(container: Container, archive: bytes, path: str) -> bool:
    return container.put_archive(path, archive)  # pyright: ignore[reportUnknownMemberType]


def _workspace_tar(clone: Path) -> bytes:
    """The tar `open` copies to `/workspace`. The checkout (`repo/`) is owned by root, readable
    by all and writable by none but root. `repo/.git`, `worktrees/` and `.incoming/` belong to
    the sandbox user, so writer nodes can add worktrees and commit, but not touch the checkout."""

    def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        git = info.name == "repo/.git" or info.name.startswith("repo/.git/")
        _own(info, SANDBOX_UID if git else 0)
        executable = info.isdir() or info.mode & 0o100
        info.mode = 0o755 if executable else 0o644
        return info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(clone, arcname="repo", filter=normalise)
        for name in ("worktrees", ".incoming"):
            directory = tarfile.TarInfo(name)
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            _own(directory, SANDBOX_UID)
            tar.addfile(directory)
    return buffer.getvalue()


def _one_file_tar(name: str, data: bytes) -> bytes:
    """A tar holding the file `name` with `data`, owned by the sandbox user."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = int(time.time())
    _own(info, SANDBOX_UID)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _own(info: tarfile.TarInfo, uid: int) -> None:
    info.uid = info.gid = uid
    info.uname = info.gname = "root" if uid == 0 else ""


def _remove(container: Container | None, volume: Volume | None) -> None:
    """Remove what `open` created; already-gone parts are fine, other errors are logged."""
    for part in (container, volume):
        if part is None:
            continue
        try:
            part.remove(force=True)
        except NotFound:
            pass
        except DockerException as e:
            log.warning("could not remove a sandbox part: %s", e)


def sweep_orphans(client: docker.DockerClient, keep: Collection[str] = frozenset()) -> int:
    """Remove every sandbox container and volume (label `agentic.run_id`) except those of the
    run ids in `keep` (runs still in flight on another worker); returns how many containers were
    removed."""
    return _sweep(client, RUN_LABEL, keep)


def _sweep(client: docker.DockerClient, label: str, keep: Collection[str] = frozenset()) -> int:
    """Remove the sandbox containers and volumes matching the `label` filter, except `keep`."""
    containers = [
        c
        for c in client.containers.list(all=True, filters={"label": label})
        if c.labels.get(RUN_LABEL) not in keep
    ]
    for container in containers:
        _remove(container, None)
    for volume in client.volumes.list(filters={"label": label}):
        labels = cast(dict[str, str], (volume.attrs or {}).get("Labels") or {})
        if labels.get(RUN_LABEL) not in keep:
            _remove(None, volume)
    return len(containers)
