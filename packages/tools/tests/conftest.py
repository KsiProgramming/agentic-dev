"""Repo tools run on both sandbox backends: the fake one needs `sh` and POSIX tools on the host,
the Docker one a daemon. Each is skipped where it cannot run. Tools are called through a real
in-memory MCP client."""

import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import docker
import pytest
from docker.errors import DockerException

from agentic_sandbox import FakeSandboxManager, RepoSource, Sandbox, SandboxManager
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import make_repo
from agentic_tools.repo import RepoLimits
from agentic_tools.testing import CallRepo, call_tool


def _posix_tools_on_host() -> bool:
    if not (shutil.which("sh") and (find := shutil.which("find"))):
        return False
    probe = subprocess.run([find, ".", "-maxdepth", "0"], capture_output=True, check=False)
    return probe.returncode == 0


def _docker_manager(local_root: Path) -> SandboxManager:
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    return DockerSandboxManager(client, local_root=local_root)


@pytest.fixture
def repos(tmp_path: Path) -> Path:
    """The allowed local root; it holds the `hello` sample repo."""
    root = tmp_path / "repos"
    make_repo(root / "hello")
    return root


@pytest.fixture(
    params=[
        pytest.param("fake"),
        pytest.param("docker", marks=pytest.mark.integration),
    ]
)
def manager(request: pytest.FixtureRequest, repos: Path) -> SandboxManager:
    if request.param == "fake":
        if not _posix_tools_on_host():
            pytest.skip("needs sh and a POSIX find on the host")
        return FakeSandboxManager(local_root=repos)
    return _docker_manager(repos)


@pytest.fixture
async def sandbox(manager: SandboxManager, repos: Path) -> AsyncIterator[Sandbox]:
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        yield box


@pytest.fixture
def call(sandbox: Sandbox) -> CallRepo:
    async def _call(
        tool: str, limits: RepoLimits | None = None, **arguments: Any
    ) -> tuple[bool, str]:
        return await call_tool(sandbox, tool, arguments, limits)

    return _call
