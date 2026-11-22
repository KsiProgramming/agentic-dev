"""Coverage of the changed lines and fail-to-pass for .NET in the real sandbox image (13.4): a C#
solution with a base commit and a writer's change, restored through the NuGet egress proxy and
tested in real job containers on network `none`, with Microsoft's collector writing Cobertura.
Needs Docker; the images are built from `packages/sandbox` and `packages/egress-proxy` if the
daemon lacks them. The first run restores from nuget.org.

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

LIB = (
    '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n'
    "    <TargetFramework>net10.0</TargetFramework>\n  </PropertyGroup>\n</Project>\n"
)
TESTS = (
    '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n'
    "    <TargetFramework>net10.0</TargetFramework>\n    <IsPackable>false</IsPackable>\n"
    "  </PropertyGroup>\n  <ItemGroup>\n"
    '    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.1" />\n'
    '    <PackageReference Include="xunit" Version="2.9.3" />\n'
    '    <PackageReference Include="xunit.runner.visualstudio" Version="3.1.5" />\n'
    '    <ProjectReference Include="../../src/Calc/Calc.csproj" />\n'
    "  </ItemGroup>\n</Project>\n"
)
CALC_BASE = (
    "namespace Calc;\n\npublic static class Calculator\n{\n"
    "    public static int Add(int a, int b) => a + b;\n}\n"
)
TESTS_BASE = (
    "using Xunit;\nnamespace Calc.Tests;\n\npublic class CalcTests\n{\n"
    "    [Fact]\n    public void AC001_Adds() => Assert.Equal(3, Calc.Calculator.Add(1, 2));\n}\n"
)
BASE = {
    "src/Calc/Calc.csproj": LIB,
    "src/Calc/Calculator.cs": CALC_BASE,
    "tests/Calc.Tests/Calc.Tests.csproj": TESTS,
    "tests/Calc.Tests/CalcTests.cs": TESTS_BASE,
}

# The change adds `Double` (line 6, run by AC002's test) and `Triple` (line 7, run by nobody).
CALC_AFTER = CALC_BASE.replace(
    "}\n",
    "    public static int Double(int x) => x * 2;\n    public static int Triple(int x) => x * 3;\n}\n",
    1,
).replace("a + b;\n    public static int Double", "a + b;\n    public static int Double")
TESTS_AFTER = TESTS_BASE.replace(
    "}\n",
    "    [Fact]\n    public void AC002_Doubles() => Assert.Equal(4, Calc.Calculator.Double(2));\n}\n",
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
def nuget(client: docker.DockerClient) -> Iterator[EgressForTests]:
    with registry_egress(client, "nuget") as proxy:
        yield proxy


@pytest.fixture(scope="module")
def run_id() -> UUID:
    return uuid4()


@pytest.fixture(scope="module")
async def sandbox(
    client: docker.DockerClient,
    nuget: EgressForTests,
    run_id: UUID,
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[Sandbox]:
    repos = tmp_path_factory.mktemp("repos")
    make_repo(repos / "app", BASE)
    manager = DockerSandboxManager(client, egress={"nuget": nuget.egress}, local_root=repos)
    async with manager.open(run_id, RepoSource(url=str(repos / "app"))) as box:
        tree = await add_worktree(box, run_id, "writer")
        write = (
            f"printf %s '{CALC_AFTER}' > src/Calc/Calculator.cs && "
            f"printf %s '{TESTS_AFTER}' > tests/Calc.Tests/CalcTests.cs"
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
            "test", {"node": "writer", "ecosystems": ["dotnet"], **arguments}
        )
    assert not result.is_error, result.content
    (check,) = (result.structured_content or {})["checks"]
    return check


@pytest.fixture(scope="module")
async def change(sandbox: Sandbox, run_id: UUID) -> dict[str, Any]:
    return await call(sandbox, run_id, coverage=True, select=["AC-001", "AC-002", "AC-003"])


async def test_the_change_builds_and_both_tests_pass(change: dict[str, Any]) -> None:
    assert (change["status"], change["passed"], change["failed"]) == ("passed", 2, 0), change


async def test_each_test_that_names_a_criterion_is_reported(change: dict[str, Any]) -> None:
    cases = {c["ids"][0]: c for c in change["cases"]}
    assert set(cases) == {"AC-001", "AC-002"}
    assert cases["AC-002"]["status"] == "passed"


async def test_the_changed_lines_are_counted_by_hand(change: dict[str, Any]) -> None:
    # The change adds lines 6 (`Double`, run by AC002) and 7 (`Triple`, run by nobody).
    assert change["coverage_reason"] is None, change
    coverage = change["coverage"]
    assert (coverage["changed"], coverage["covered"]) == (2, 1), coverage
    assert coverage["files"][0]["path"] == "src/Calc/Calculator.cs"
    assert coverage["files"][0]["uncovered"] == [[7, 7]]


async def test_on_the_base_a_test_project_that_does_not_build_fails_before(
    sandbox: Sandbox, run_id: UUID
) -> None:
    # The change's test file lays over the base, where `Double` does not exist: no build.
    base = await call(sandbox, run_id, on="base", select=["AC-001", "AC-002"])

    assert (base["status"], base["reason"]) == ("failed", "the base run did not build"), base
    assert base["cases"] == []
