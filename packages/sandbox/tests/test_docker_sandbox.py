"""The Docker backend against a real daemon; skipped where none is reachable."""

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import docker
import pytest
from docker.errors import DockerException

from agentic_sandbox import RepoSource, SandboxError, SandboxManager
from agentic_sandbox.docker_backend import RUN_LABEL, DockerSandboxManager, sweep_orphans
from agentic_sandbox.testing import ensure_sandbox_image

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> Iterator[docker.DockerClient]:
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    yield client
    client.close()


@pytest.fixture
def manager(client: docker.DockerClient, repos: Path) -> DockerSandboxManager:
    return DockerSandboxManager(client, local_root=repos)


def labelled(client: docker.DockerClient, run_id: UUID) -> list[str]:
    containers = client.containers.list(all=True, filters={"label": f"{RUN_LABEL}={run_id}"})
    volumes = client.volumes.list(filters={"label": f"{RUN_LABEL}={run_id}"})
    return [c.name or "" for c in containers] + [v.name or "" for v in volumes]


async def test_the_container_holds_the_clone(manager: DockerSandboxManager, repos: Path) -> None:
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        result = await box.exec(["find", ".", "-name", "*.py"])

    assert result.exit_code == 0
    assert sorted(result.stdout.split()) == [
        "./src/app.py",
        "./src/pkg/__init__.py",
        "./src/pkg/deep/mod.py",
    ]


async def test_the_container_and_volume_are_removed_after_the_run(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    run_id = uuid4()
    async with manager.open(run_id, RepoSource(url=str(repos / "hello"))):
        assert len(labelled(client, run_id)) == 2

    assert labelled(client, run_id) == []


async def test_they_are_removed_when_the_run_fails(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    run_id = uuid4()
    with pytest.raises(RuntimeError, match="boom"):
        async with manager.open(run_id, RepoSource(url=str(repos / "hello"))):
            raise RuntimeError("boom")

    assert labelled(client, run_id) == []


async def test_a_failed_clone_creates_nothing(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    run_id = uuid4()
    with pytest.raises(SandboxError, match="could not clone"):
        async with manager.open(run_id, RepoSource(url=str(repos / "missing"))):
            pytest.fail("the sandbox must not open")

    assert labelled(client, run_id) == []


async def test_the_container_has_no_network(manager: DockerSandboxManager, repos: Path) -> None:
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        result = await box.exec(["wget", "-q", "-T", "3", "-O", "-", "http://1.1.1.1"])
        interfaces = await box.exec(["ls", "/sys/class/net"])

    assert result.exit_code != 0
    assert interfaces.stdout.split() == ["lo"]


async def test_it_runs_as_non_root_on_a_read_only_root(
    manager: DockerSandboxManager, repos: Path
) -> None:
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        uid = await box.exec(["id", "-u"])
        root_write = await box.exec(["touch", "/etc/pwned"])
        repo_write = await box.exec(["touch", "README.md"])

    assert uid.stdout.strip() == "1000"
    assert root_write.exit_code != 0
    assert repo_write.exit_code != 0  # the shared checkout is read-only; writers get worktrees


async def test_a_slow_command_times_out(manager: DockerSandboxManager, repos: Path) -> None:
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        result = await box.exec(["sleep", "30"], timeout_s=1)

    assert result.exit_code != 0
    assert "timed out" in result.stderr


async def test_sweep_removes_leftover_sandboxes(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    run_id = uuid4()
    leftover = manager.open(run_id, RepoSource(url=str(repos / "hello")))
    await leftover.__aenter__()  # never exited, as if the worker died
    assert labelled(client, run_id)

    assert sweep_orphans(client) >= 1
    assert labelled(client, run_id) == []


async def test_sweep_keeps_sandboxes_of_runs_in_flight(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    run_id = uuid4()
    async with manager.open(run_id, RepoSource(url=str(repos / "hello"))):
        sweep_orphans(client, keep={str(run_id)})
        assert labelled(client, run_id)


async def test_reopening_a_run_replaces_the_sandbox_it_left(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    """A resumed run gets a fresh sandbox even if its earlier attempt's is still there."""
    run_id = uuid4()
    leftover = manager.open(run_id, RepoSource(url=str(repos / "hello")))
    await leftover.__aenter__()  # never exited, as if the worker died

    async with manager.open(run_id, RepoSource(url=str(repos / "hello"))) as box:
        assert (await box.exec(["cat", "README.md"])).exit_code == 0
        assert len(labelled(client, run_id)) == 2  # one container and its volume
    assert labelled(client, run_id) == []


def test_the_docker_manager_implements_the_protocol(client: docker.DockerClient) -> None:
    _: SandboxManager = DockerSandboxManager(client)


async def test_a_kept_sandbox_is_reopened_as_it_was(
    client: docker.DockerClient, manager: DockerSandboxManager, repos: Path
) -> None:
    """A run paused at a gate keeps its container and volume; the attempt that continues it
    attaches to them again, with what was written before the gate."""
    run_id, repo = uuid4(), RepoSource(url=str(repos / "hello"))
    async with manager.open(run_id, repo) as box:
        written = await box.exec(["sh", "-c", "echo before > /workspace/worktrees/marker"])
        assert written.exit_code == 0
        manager.keep(run_id)
    assert len(labelled(client, run_id)) == 2

    async with manager.open(run_id, repo, reuse=True) as box:
        assert (await box.exec(["cat", "/workspace/worktrees/marker"])).stdout == "before\n"
    assert labelled(client, run_id) == []
