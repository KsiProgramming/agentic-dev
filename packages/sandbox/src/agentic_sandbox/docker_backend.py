"""Sandboxes as local Docker containers, one per run.

The repo is cloned on the worker and copied into a per-run volume mounted at `/workspace`. The
container has no network, a read-only root filesystem, no capabilities and runs as a non-root
user; the clone is owned by root, so in this phase agents can read it but not change it. Every
container and volume carries the `agentic.run_id` label, so leftovers can be swept.

docker-py is blocking, so its calls run in threads.
"""

import asyncio
import io
import logging
import math
import shutil
import tarfile
import tempfile
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.models.volumes import Volume
from docker.types import Mount

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import DEFAULT_EXEC_TIMEOUT_S, ExecResult, decode_capped
from agentic_sandbox.source import RepoSource, clone_shallow

log = logging.getLogger("agentic_sandbox")

DEFAULT_IMAGE = "alpine:3.20"
RUN_LABEL = "agentic.run_id"
WORKSPACE = "/workspace"
REPO_DIR = f"{WORKSPACE}/repo"
SANDBOX_USER = "1000:1000"
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

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = DEFAULT_EXEC_TIMEOUT_S
    ) -> ExecResult:
        # The container stops the command itself; the thread only waits for it.
        cmd = ["timeout", str(max(1, math.ceil(timeout_s))), *argv]
        try:
            exit_code, out, err = await asyncio.to_thread(self._exec, cmd)
        except DockerException as e:
            log.warning("sandbox exec failed: %s", e)
            raise SandboxError("the sandbox is not available") from e
        stdout, out_cut = decode_capped(out)
        stderr, err_cut = decode_capped(err)
        if exit_code in _TIMED_OUT_CODES:
            exit_code = TIMED_OUT
            stderr += f"\ntimed out after {timeout_s:g} s"
        return ExecResult(exit_code, stdout, stderr, truncated=out_cut or err_cut)

    def _exec(self, cmd: list[str]) -> tuple[int, bytes, bytes]:
        result = self._container.exec_run(cmd, user=SANDBOX_USER, workdir=REPO_DIR, demux=True)
        # With `demux=True` the output is a `(stdout, stderr)` pair, each `None` when empty.
        out, err = cast(tuple[bytes | None, bytes | None], result.output)
        return result.exit_code or 0, out or b"", err or b""


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
                volume = await asyncio.to_thread(
                    self._client.volumes.create, name=name, labels={RUN_LABEL: str(run_id)}
                )
                container = await asyncio.to_thread(self._create, name, run_id)
                if not await asyncio.to_thread(_put_archive, container, archive):
                    raise SandboxError("could not copy the repo into the sandbox")
                await asyncio.to_thread(container.start)
            except DockerException as e:
                log.warning("sandbox %s could not be created: %s", name, e)
                raise SandboxError("could not create the sandbox container") from e
            log.info("sandbox %s ready in %.2f s", name, time.monotonic() - started)
            yield DockerSandbox(container)
        finally:
            await asyncio.to_thread(_remove, container, volume)
            log.info("sandbox %s removed after %.2f s", name, time.monotonic() - started)

    async def _clone(self, repo: RepoSource) -> bytes:
        """A tar of a shallow clone of `repo`, rooted at `repo/`."""
        staging = Path(tempfile.mkdtemp(prefix="agentic-clone-"))
        try:
            await clone_shallow(repo, staging / "repo", local_root=self._local_root)
            return await asyncio.to_thread(_tar, staging / "repo", "repo")
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
            self._client.images.pull(self._image)
            return create()


def _put_archive(container: Container, archive: bytes) -> bool:
    return container.put_archive(WORKSPACE, archive)  # pyright: ignore[reportUnknownMemberType]


def _tar(path: Path, arcname: str) -> bytes:
    """`path` as a tar owned by root, readable by all and writable by none but root."""

    def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        executable = info.isdir() or info.mode & 0o100
        info.mode = 0o755 if executable else 0o644
        return info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(path, arcname=arcname, filter=normalise)
    return buffer.getvalue()


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


def sweep_orphans(client: docker.DockerClient) -> int:
    """Remove every sandbox container and volume (label `agentic.run_id`); returns how many
    containers were removed. Call it when no run is in flight on this Docker host."""
    containers = client.containers.list(all=True, filters={"label": RUN_LABEL})
    for container in containers:
        _remove(container, None)
    for volume in client.volumes.list(filters={"label": RUN_LABEL}):
        _remove(None, volume)
    return len(containers)
