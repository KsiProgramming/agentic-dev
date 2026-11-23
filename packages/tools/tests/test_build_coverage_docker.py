"""Coverage of the changed lines and fail-to-pass in the real sandbox image (13.4): a Python repo
with a base commit and a writer's change, its tests run in real job containers on network `none`.
Needs Docker; the images are built from `packages/sandbox` and `packages/egress-proxy` if the
daemon lacks them. The first run downloads pytest from PyPI.

Run this file by itself: never `packages/sandbox/tests` as a whole (its sweep test removes other
stacks' sandboxes)."""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID, uuid4

import docker
import pytest
from docker.errors import DockerException
from mcp import Client

from agentic_runtime import ReadableWriter, ReadableWriters
from agentic_sandbox import RepoSource, Sandbox, add_worktree, branch_name
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import EgressForTests, ensure_sandbox_image, make_repo, registry_egress
from agentic_tools.build import build_build_server

pytestmark = pytest.mark.integration

# The base: `add` is covered by AC-001's test, which already passes. `test_network_is_off` passes
# only when a job has no route out.
BASE = {
    "requirements.txt": "pytest==8.4.2\n",
    "pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["."]\n',
    "calc.py": "def add(a, b):\n    return a + b\n",
    "tests/test_calc.py": (
        "import socket\n"
        "import pytest\n"
        "from calc import add\n\n\n"
        "def test_ac_001_adds():\n    assert add(1, 2) == 3\n\n\n"
        "def test_network_is_off():\n"
        "    with pytest.raises(OSError):\n"
        '        socket.create_connection(("pypi.org", 443), timeout=3)\n'
    ),
}

# The change: `double` (lines 5-6 of calc.py) is run by AC-002's test, which cannot even import
# on the base; `triple` (lines 9-10) is run by no test. Nothing tests AC-003.
CALC_AFTER = (
    "def add(a, b):\n    return a + b\n\n\n"
    "def double(x):\n    return x * 2\n\n\n"
    "def triple(x):\n    return x * 3\n"
)
TESTS_AFTER = (
    BASE["tests/test_calc.py"] + "\n\n"
    "def test_ac_002_doubles():\n    from calc import double\n    assert double(2) == 4\n"
)


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
def pypi(client: docker.DockerClient) -> Iterator[EgressForTests]:
    with registry_egress(client, "pypi") as proxy:
        yield proxy


@pytest.fixture(scope="module")
def run_id() -> UUID:
    return uuid4()


@pytest.fixture(scope="module")
async def sandbox(
    client: docker.DockerClient,
    pypi: EgressForTests,
    run_id: UUID,
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[Sandbox]:
    repos = tmp_path_factory.mktemp("repos")
    make_repo(repos / "app", BASE)
    manager = DockerSandboxManager(client, egress={"pypi": pypi.egress}, local_root=repos)
    async with manager.open(run_id, RepoSource(url=str(repos / "app"))) as box:
        tree = await add_worktree(box, run_id, "writer")
        write = (
            f"printf %s '{CALC_AFTER}' > calc.py && printf %s '{TESTS_AFTER}' > tests/test_calc.py"
        )
        done = await tree.exec(
            [
                "sh",
                "-c",
                f"{write} && git add -A && git -c user.name=t -c user.email=t@e.invalid "
                "-c commit.gpgsign=false commit -q -m change",
            ]
        )
        assert done.exit_code == 0, done.stderr
        yield box


async def call(sandbox: Sandbox, run_id: UUID, **arguments: Any) -> dict[str, Any]:
    readable = ReadableWriters(lambda node: branch_name(run_id, node))
    readable.set([ReadableWriter("writer", "writer")], known=("writer",))
    async with Client(build_build_server(sandbox, readable=readable)) as client:
        result = await client.call_tool(
            "test", {"node": "writer", "ecosystems": ["python"], **arguments}
        )
    assert not result.is_error, result.content
    return result.structured_content or {}


def only(report: dict[str, Any]) -> dict[str, Any]:
    (check,) = report["checks"]
    return check


@pytest.fixture(scope="module")
async def change(sandbox: Sandbox, run_id: UUID) -> dict[str, Any]:
    return only(await call(sandbox, run_id, coverage=True, select=["AC-001", "AC-002", "AC-003"]))


async def test_the_changed_lines_are_counted_by_hand(change: dict[str, Any]) -> None:
    # The change adds calc.py lines 3-10; the executable ones are 5, 6, 9 and 10 (blank lines are
    # not). The `def` lines run when the module is imported, `double`'s body is run by AC-002's
    # test and `triple`'s body (line 10) by nobody: 3 of 4.
    coverage = change["coverage"]
    assert (coverage["changed"], coverage["covered"]) == (4, 3)
    [file] = coverage["files"]
    assert file["path"] == "calc.py"
    assert file["uncovered"] == [[10, 10]]
    assert change["coverage_reason"] is None


async def test_every_test_passes_on_the_change_and_runs_with_no_network(
    change: dict[str, Any],
) -> None:
    # `test_network_is_off` passes only when the job could not reach pypi.org.
    assert (change["status"], change["passed"], change["failed"]) == ("passed", 3, 0)


async def test_the_change_reports_the_tests_that_name_a_criterion(change: dict[str, Any]) -> None:
    cases = {c["ids"][0]: c for c in change["cases"]}
    assert set(cases) == {"AC-001", "AC-002"}  # AC-003 has no test
    assert cases["AC-002"]["status"] == "passed"
    assert cases["AC-002"]["name"].endswith("::test_ac_002_doubles")
    assert cases["AC-002"]["file"] == "tests/test_calc.py"


async def test_on_the_base_a_new_test_that_cannot_import_is_not_a_pass(
    sandbox: Sandbox, run_id: UUID
) -> None:
    base = only(await call(sandbox, run_id, on="base", select=["AC-001", "AC-002"]))

    passed = {c["ids"][0] for c in base["cases"] if c["status"] == "passed"}
    # AC-001's test passes on both (not proven); AC-002's has no passing result before: proven.
    assert passed == {"AC-001"}
    assert base["coverage"] is None


async def test_on_base_needs_a_selection_and_no_coverage(sandbox: Sandbox, run_id: UUID) -> None:
    readable = ReadableWriters(lambda node: branch_name(run_id, node))
    readable.set([ReadableWriter("writer", "writer")], known=("writer",))
    async with Client(build_build_server(sandbox, readable=readable)) as client:
        no_ids = await client.call_tool("test", {"node": "writer", "on": "base"})
        with_coverage = await client.call_tool(
            "test", {"node": "writer", "on": "base", "select": ["AC-001"], "coverage": True}
        )

    assert no_ids.is_error and with_coverage.is_error


async def test_the_checkout_and_the_writers_worktree_are_unchanged(
    sandbox: Sandbox, change: dict[str, Any], run_id: UUID
) -> None:
    built = await sandbox.exec(
        ["find", ".", "-name", ".venv", "-o", "-name", ".agentic-*", "-o", "-name", "__pycache__"]
    )
    staged = await sandbox.exec(["ls", "-A", sandbox.staging_dir])
    status = await sandbox.exec(["sh", "-c", "git status --porcelain"])

    assert built.stdout == ""
    assert staged.stdout.split() == [".cache"]  # every work copy and base tree is gone
    assert status.stdout.strip() == ""
