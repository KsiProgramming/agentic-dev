"""Job containers (4.8) against a real daemon: they work on the sandbox's files, are always
removed, and reach nothing but NuGet, through the egress proxy. Skipped where Docker is not
reachable."""

import contextlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import docker
import pytest
from docker.errors import DockerException

from agentic_sandbox import RepoSource, Sandbox, SandboxError
from agentic_sandbox.docker_backend import (
    JOB_LABEL,
    RUN_LABEL,
    DockerSandboxManager,
    JobLimits,
)
from agentic_sandbox.testing import EgressForTests, ensure_sandbox_image, nuget_egress

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


@pytest.fixture(scope="module")
def egress(client: docker.DockerClient) -> Iterator[EgressForTests]:
    with nuget_egress(client) as egress:
        yield egress


@pytest.fixture
def run_id() -> UUID:
    return uuid4()


@pytest.fixture
async def sandbox(
    client: docker.DockerClient, egress: EgressForTests, repos: Path, run_id: UUID
) -> AsyncIterator[Sandbox]:
    manager = DockerSandboxManager(
        client, job_limits=JobLimits(memory="256m"), nuget=egress.nuget, local_root=repos
    )
    async with manager.open(run_id, RepoSource(url=str(repos / "hello"))) as box:
        yield box


def jobs_of(client: docker.DockerClient, run_id: UUID) -> list[str]:
    containers = client.containers.list(
        all=True, filters={"label": [f"{RUN_LABEL}={run_id}", JOB_LABEL]}
    )
    return [c.name or "" for c in containers]


async def workdir(sandbox: Sandbox) -> str:
    """A directory under the staging directory for a job to work in."""
    path = f"{sandbox.staging_dir}/job-{uuid4().hex[:8]}"
    result = await sandbox.exec(["mkdir", path])
    assert result.exit_code == 0, result.stderr
    return path


async def test_a_job_works_on_the_sandbox_files_and_is_removed(
    sandbox: Sandbox, client: docker.DockerClient, run_id: UUID
) -> None:
    cwd = await workdir(sandbox)
    script = (
        'cat /workspace/repo/README.md; echo made > out.txt; echo oops >&2; id -u; echo "$HOME"'
    )

    result = await sandbox.run_job(
        ["sh", "-c", script], network="none", cwd=cwd, timeout_s=30, env={"HOME": cwd}
    )

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["# Hello repo", "1000", cwd]
    assert result.stderr == "oops\n"
    made = await sandbox.exec(["cat", f"{cwd}/out.txt"])
    assert made.stdout == "made\n"
    assert jobs_of(client, run_id) == []


async def test_a_failed_job_reports_its_exit_code_and_is_removed(
    sandbox: Sandbox, client: docker.DockerClient, run_id: UUID
) -> None:
    result = await sandbox.run_job(
        ["sh", "-c", "exit 7"], network="none", cwd=await workdir(sandbox), timeout_s=30
    )

    assert result.exit_code == 7
    assert jobs_of(client, run_id) == []


async def test_a_job_past_its_timeout_is_stopped_and_removed(
    sandbox: Sandbox, client: docker.DockerClient, run_id: UUID
) -> None:
    result = await sandbox.run_job(
        ["sleep", "60"], network="none", cwd=await workdir(sandbox), timeout_s=2
    )

    assert result.exit_code == 124
    assert "timed out" in result.stderr
    assert jobs_of(client, run_id) == []


async def test_a_job_cannot_change_the_checkout(sandbox: Sandbox) -> None:
    result = await sandbox.run_job(
        ["sh", "-c", "echo x > /workspace/repo/README.md"],
        network="none",
        cwd=await workdir(sandbox),
        timeout_s=30,
    )

    assert result.exit_code != 0
    readme = await sandbox.exec(["cat", "README.md"])
    assert readme.stdout == "# Hello repo\n"


async def test_a_job_works_only_under_the_staging_directory(sandbox: Sandbox) -> None:
    for cwd in (sandbox.workdir, sandbox.staging_dir, f"{sandbox.staging_dir}/../repo"):
        with pytest.raises(ValueError, match="staging"):
            await sandbox.run_job(["true"], network="none", cwd=cwd, timeout_s=5)


async def test_a_job_with_no_network_reaches_nothing(sandbox: Sandbox) -> None:
    result = await sandbox.run_job(
        ["wget", "-q", "-T", "5", "-O", "/dev/null", "https://api.nuget.org/v3/index.json"],
        network="none",
        cwd=await workdir(sandbox),
        timeout_s=30,
    )

    assert result.exit_code != 0


async def test_a_nuget_job_reaches_nuget_and_nothing_else(
    sandbox: Sandbox, egress: EgressForTests
) -> None:
    # git speaks HTTPS through the proxy variables (busybox wget ignores them); neither URL is a
    # git repo, so only how the request fails tells where it got.
    cwd = await workdir(sandbox)

    async def reach(url: str, *, proxy: bool = True) -> str:
        argv = ["git", *([] if proxy else ["-c", "http.proxy="]), "ls-remote", url]
        env = {} if proxy else {"https_proxy": "", "HTTPS_PROXY": ""}
        result = await sandbox.run_job(argv, network="nuget", cwd=cwd, timeout_s=30, env=env)
        assert result.exit_code != 0
        return result.stderr

    through = await reach("https://api.nuget.org/v3/index.json")
    assert "CONNECT tunnel failed" not in through and "resolve" not in through
    assert "CONNECT tunnel failed, response 403" in await reach("https://example.com/")
    # Around the proxy: the network is internal, so there is no route (not even DNS).
    assert "resolve host" in await reach("https://api.nuget.org/v3/index.json", proxy=False)
    assert "example.com" in egress.refused_hosts()
    assert "api.nuget.org" not in egress.refused_hosts()


async def test_without_a_proxy_jobs_have_no_nuget_network(
    client: docker.DockerClient, repos: Path
) -> None:
    manager = DockerSandboxManager(client, local_root=repos)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "hello"))) as box:
        assert box.job_networks == frozenset({"none"})
        with pytest.raises(SandboxError, match="nuget"):
            await box.run_job(["true"], network="nuget", cwd=await workdir(box), timeout_s=5)


async def test_discarding_a_run_removes_a_job_it_left_behind(
    client: docker.DockerClient, repos: Path
) -> None:
    # Only this run's label is swept, never the host's other sandboxes.
    run_id = uuid4()
    left = client.containers.create(
        "agentic-dev/sandbox:dev",
        command=["true"],
        name=f"agentic-job-{run_id}-left",
        labels={RUN_LABEL: str(run_id), JOB_LABEL: "1"},
    )
    try:
        await DockerSandboxManager(client, local_root=repos).discard(run_id)
        assert jobs_of(client, run_id) == []
    finally:
        with contextlib.suppress(DockerException):
            left.remove(force=True)
