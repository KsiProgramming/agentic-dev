import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import docker
import pytest
from docker.errors import DockerException

from agentic_sandbox import FakeSandboxManager, RepoSource, Sandbox, SandboxManager
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import ensure_sandbox_image, make_repo

RUN_ID = UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def repos(tmp_path: Path) -> Path:
    """The allowed local root; it holds the `hello` sample repo."""
    root = tmp_path / "repos"
    make_repo(root / "hello")
    return root


@pytest.fixture(params=["fake", pytest.param("docker", marks=pytest.mark.integration)])
def backend(request: pytest.FixtureRequest, repos: Path) -> tuple[str, SandboxManager]:
    if request.param == "fake":
        if not (shutil.which("sh") and shutil.which("git")):
            pytest.skip("needs sh and git on the host")
        return "fake", FakeSandboxManager(local_root=repos)
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    return "docker", DockerSandboxManager(client, local_root=repos)


@pytest.fixture
async def sandbox(backend: tuple[str, SandboxManager], repos: Path) -> AsyncIterator[Sandbox]:
    async with backend[1].open(RUN_ID, RepoSource(url=str(repos / "hello"))) as box:
        yield box
