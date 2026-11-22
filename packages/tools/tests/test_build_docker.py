"""`build.restore` in the real sandbox image (13.2): a Node and a Python repo restored through the
registry's egress proxy, built with no network, and a request to any other host refused and
logged. Needs Docker; the images are built from `packages/sandbox` and `packages/egress-proxy`
if the daemon lacks them. The first run downloads from npm and PyPI."""

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

import docker
import pytest
from docker.errors import DockerException
from mcp import Client

from agentic_sandbox import RepoSource, Sandbox
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import (
    EgressForTests,
    ensure_sandbox_image,
    make_repo,
    registry_egress,
)
from agentic_tools.build import build_build_server

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures" / "restore"


def _files(directory: str) -> dict[str, str]:
    root = FIXTURES / directory
    return {
        f"{directory}/{p.relative_to(root).as_posix()}": p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# The repo's own package sources: a restore never reads them.
HOSTILE_NPMRC = "registry=https://registry.evil.example/\n"
HOSTILE_UV = 'index-url = "https://pypi.evil.example/simple"\n'


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
def proxies(client: docker.DockerClient) -> Iterator[dict[str, EgressForTests]]:
    with ExitStack() as stack:
        yield {
            "npm": stack.enter_context(registry_egress(client, "npm")),
            "pypi": stack.enter_context(registry_egress(client, "pypi")),
        }


@pytest.fixture(scope="module")
async def sandbox(
    client: docker.DockerClient,
    proxies: dict[str, EgressForTests],
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[Sandbox]:
    repos = tmp_path_factory.mktemp("repos")
    files = {
        **_files("node"),
        **_files("python"),
        "node/.npmrc": HOSTILE_NPMRC,
        "python/uv.toml": HOSTILE_UV,
    }
    make_repo(repos / "app", files)
    egress = {name: p.egress for name, p in proxies.items()}
    manager = DockerSandboxManager(
        client,
        egress={"npm": egress["npm"], "pypi": egress["pypi"]},
        local_root=repos,
    )
    async with manager.open(uuid4(), RepoSource(url=str(repos / "app"))) as box:
        yield box


async def _restore(sandbox: Sandbox, **arguments: Any) -> dict[str, Any]:
    async with Client(build_build_server(sandbox)) as client:
        result = await client.call_tool("restore", arguments)
    assert not result.is_error, result.content
    return result.structured_content or {}


@pytest.fixture(scope="module")
async def report(sandbox: Sandbox) -> dict[str, Any]:
    return await _restore(sandbox)


def _checks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["path"]: c for c in report["checks"]}


async def test_both_repos_restore_and_build(report: dict[str, Any]) -> None:
    checks = _checks(report)

    assert {path: (c["status"], c["reason"]) for path, c in checks.items()} == {
        "node": ("ran", None),
        "python": ("ran", None),
    }
    assert (checks["node"]["manager"], checks["node"]["lockfile"]) == ("pnpm", "pnpm-lock.yaml")
    assert (checks["python"]["manager"], checks["python"]["lockfile"]) == ("uv", "uv.lock")
    assert checks["node"]["packages"] and checks["python"]["packages"]
    assert report["counts"] == {"ran": 2, "skipped": 0, "failed": 0}


async def test_the_node_build_ran_offline_with_scripts_after_the_restore(
    report: dict[str, Any],
) -> None:
    """The fixture's `build.js` exits 5 if its `preinstall` ran while the proxy was set and 3 if
    the network is reachable: a pass means the restore ran no script, the scripts ran in the
    build job, and the build job had no route out."""
    node = _checks(report)["node"]

    assert node["status"] == "ran"
    assert node["build_ms"] is not None


async def test_the_repos_own_package_sources_were_never_used(
    proxies: dict[str, EgressForTests], report: dict[str, Any]
) -> None:
    for name, proxy in proxies.items():
        refused = proxy.refused_hosts()
        assert not {h for h in refused if "evil" in h}, name


async def test_each_registrys_proxy_refused_nothing_a_restore_needs(
    proxies: dict[str, EgressForTests], report: dict[str, Any]
) -> None:
    assert proxies["npm"].refused_hosts() <= {"registry.yarnpkg.com"}
    assert proxies["pypi"].refused_hosts() == set()


async def test_a_job_reaches_its_own_registry_only_and_the_refusal_is_logged(
    sandbox: Sandbox, proxies: dict[str, EgressForTests], report: dict[str, Any]
) -> None:
    work = f"{sandbox.staging_dir}/probe-{uuid4().hex[:8]}"
    await sandbox.exec(["mkdir", work])

    async def reach(network: Any, url: str) -> str:
        result = await sandbox.run_job(
            ["git", "ls-remote", url], network=network, cwd=work, timeout_s=30
        )
        assert result.exit_code != 0
        return result.stderr

    assert "CONNECT tunnel failed, response 403" in await reach("npm", "https://github.com/a/b")
    assert "CONNECT tunnel failed, response 403" in await reach("npm", "https://pypi.org/")
    assert "CONNECT tunnel failed, response 403" in await reach(
        "pypi", "https://registry.npmjs.org/"
    )
    assert {"github.com", "pypi.org"} <= proxies["npm"].refused_hosts()
    assert "registry.npmjs.org" in proxies["pypi"].refused_hosts()
    await sandbox.exec(["rm", "-rf", "--", work])


async def test_the_checkout_is_left_as_it_was(sandbox: Sandbox, report: dict[str, Any]) -> None:
    built = await sandbox.exec(["find", ".", "-name", "node_modules", "-o", "-name", ".venv"])
    staged = await sandbox.exec(["ls", "-A", sandbox.staging_dir])

    assert built.stdout == ""
    assert staged.stdout.split() == [".cache"]  # the caches stay; every work copy is gone


async def test_a_path_restores_only_its_part(sandbox: Sandbox) -> None:
    report = await _restore(sandbox, path="python", ecosystems=["python"])

    assert [(c["path"], c["status"]) for c in report["checks"]] == [("python", "ran")]


async def test_a_path_outside_the_repo_is_refused(sandbox: Sandbox) -> None:
    async with Client(build_build_server(sandbox)) as client:
        result = await client.call_tool("restore", {"path": "../.."})

    assert result.is_error


async def test_without_a_proxy_a_registry_is_not_configured(
    client: docker.DockerClient, tmp_path: Path
) -> None:
    repos = tmp_path / "repos"
    make_repo(repos / "app", _files("node"))
    manager = DockerSandboxManager(client, local_root=repos)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "app"))) as box:
        report = await _restore(box)

    (check,) = report["checks"]
    assert (check["status"], check["reason"]) == (
        "skipped",
        "skipped: npm restore is not configured",
    )
