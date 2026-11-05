"""`scan.lint` on C# projects in the real sandbox image (4.8): restored through the NuGet egress
proxy, built with no network, each project's analyzer findings reported at the repo's own
severities, and every module we cannot build reported with its reason. Needs Docker; the images
are built from `packages/sandbox` and `packages/egress-proxy` if the daemon lacks them. The first
run restores from nuget.org."""

from collections.abc import AsyncIterator, Iterator
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
    nuget_egress,
)
from agentic_tools.scan import build_scan_server

pytestmark = pytest.mark.integration

_NET10 = "<TargetFramework>net10.0</TargetFramework>"


def _project(properties: str = _NET10, items: str = "") -> str:
    return (
        f'<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    {properties}\n'
        f"  </PropertyGroup>\n  <ItemGroup>{items}</ItemGroup>\n</Project>\n"
    )


# A .NET monorepo, one module per case. The root `global.json` pins an SDK the image does not
# have: the build must still run, with the image's SDK.
DOTNET_REPO: dict[str, str] = {
    "global.json": '{"sdk": {"version": "8.0.100", "rollForward": "latestFeature"}}\n',
    # No analysis set up: the SDK's defaults (`platform-default`).
    "clean/Clean.csproj": _project(),
    "clean/Ok.cs": "namespace Clean;\n\npublic static class Ok\n{\n"
    "    public static int One() => 1;\n}\n",
    # The repo's `.editorconfig` raises two rules; one of them has no code fix (CA2201). A
    # `#pragma` suppresses a third finding.
    "warnings/Warnings.csproj": _project(),
    "warnings/.editorconfig": "root = true\n\n[*.cs]\n"
    "dotnet_diagnostic.CA1822.severity = warning\n"
    "dotnet_diagnostic.CA2201.severity = warning\n",
    "warnings/Calc.cs": (
        "namespace Warnings;\n"
        "\n"
        "public class Calc\n"
        "{\n"
        "    public int Add(int a, int b) => a + b;\n"
        "\n"
        '    public void Fail() => throw new System.Exception("boom");\n'
        "\n"
        "#pragma warning disable CA1822\n"
        "    public int Quiet() => 2;\n"
        "#pragma warning restore CA1822\n"
        "}\n"
    ),
    # An analyzer package from nuget.org, and an older target framework (its reference pack is
    # restored too). Two target frameworks report each finding once.
    "packages/Packages.csproj": _project(
        "<TargetFrameworks>net8.0;net10.0</TargetFrameworks>",
        '<PackageReference Include="StyleCop.Analyzers" Version="1.1.118" PrivateAssets="all" />',
    ),
    "packages/Program.cs": "namespace Packages\n{\n    public static class Program\n    {\n"
    "        public static int Main() => 0;\n    }\n}\n",
    # A package only a private feed has: the repo's own nuget.config is never read.
    "feed/Feed.csproj": _project(
        items='<PackageReference Include="Contoso.Internal.Only" Version="1.0.0" />'
    ),
    "feed/nuget.config": '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n'
    "  <packageSources>\n"
    '    <add key="contoso" value="https://pkgs.contoso.example/nuget/v3/index.json" />\n'
    "  </packageSources>\n</configuration>\n",
    "feed/F.cs": "namespace Feed;\n\npublic static class F\n{\n}\n",
    # Code that does not compile: a failed check, not analyzer noise.
    "broken/Broken.csproj": _project(),
    "broken/C.cs": "namespace Broken;\n\npublic static class C\n{\n"
    "    public static int M() => Missing.Value;\n}\n",
    # F#: no linter.
    "fsharp/Lib.fsproj": _project(),
    "fsharp/Lib.fs": "module Lib\n\nlet one = 1\n",
}


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


@pytest.fixture(scope="module")
async def sandbox(
    client: docker.DockerClient, egress: EgressForTests, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[Sandbox]:
    repos = tmp_path_factory.mktemp("repos")
    make_repo(repos / "dotnet", DOTNET_REPO)
    manager = DockerSandboxManager(client, nuget=egress.nuget, local_root=repos)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "dotnet"))) as box:
        yield box


async def _lint(sandbox: Sandbox, **arguments: Any) -> dict[str, Any]:
    async with Client(build_scan_server(sandbox)) as client:
        result = await client.call_tool("lint", arguments)
    assert not result.is_error, result.content
    return result.structured_content or {}


@pytest.fixture(scope="module")
async def report(sandbox: Sandbox) -> dict[str, Any]:
    return await _lint(sandbox)


def _checks(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["path"]: c for c in report["checks"]}


def _found(report: dict[str, Any], module: str) -> list[tuple[str, int, str]]:
    return sorted(
        (f["rule"], f["line"], f["severity"])
        for f in report["findings"]
        if f["path"].startswith(f"{module}/")
    )


async def test_each_csharp_module_is_one_check(report: dict[str, Any]) -> None:
    checks = _checks(report)

    assert {path: (c["status"], c["reason"]) for path, c in checks.items()} == {
        "clean": ("ran", None),
        "warnings": ("ran", None),
        "packages": ("ran", None),
        "feed": ("failed", "restore failed: a package is not on nuget.org"),
        "broken": ("failed", "does not compile (1 error)"),
        "fsharp": ("skipped", "no supported linter for fsharp"),
    }
    assert checks["clean"]["config"] == "platform-default"
    assert checks["warnings"]["config"] == "repo"
    assert checks["packages"]["config"] == "repo"
    # The image's SDK built it, whatever `global.json` pins.
    assert checks["clean"]["version"].startswith("10.")
    assert all(c["tool"] in ("dotnet", None) for c in checks.values())


async def test_findings_follow_the_repos_severities(report: dict[str, Any]) -> None:
    # `Add` and `Fail` touch no instance data (CA1822); `Fail` throws `Exception` (CA2201, no code
    # fix). `Quiet` is suppressed by its `#pragma`.
    assert _found(report, "warnings") == [
        ("CA1822", 5, "low"),
        ("CA1822", 7, "low"),
        ("CA2201", 7, "low"),
    ]
    ca2201 = next(f for f in report["findings"] if f["rule"] == "CA2201")
    assert ca2201["help_url"].endswith("/ca2201")
    assert ca2201["config"] == "repo"
    assert ca2201["fingerprint"]


async def test_analyzer_packages_are_restored_and_reported_once(report: dict[str, Any]) -> None:
    found = _found(report, "packages")

    assert found and all(rule.startswith("SA") for rule, _, _ in found)
    # Built for net8.0 and net10.0, each finding is listed once.
    assert len(found) == len(set(found))
    assert _checks(report)["packages"]["findings"] == len(found)


async def test_nothing_is_reported_for_modules_that_could_not_build(
    report: dict[str, Any],
) -> None:
    for module in ("feed", "broken", "fsharp"):
        assert _found(report, module) == []


async def test_the_restore_reaches_nuget_only(egress: EgressForTests) -> None:
    refused = egress.refused_hosts()

    assert "pkgs.contoso.example" not in refused
    assert "api.nuget.org" not in refused


async def test_the_checkout_is_left_as_it_was(sandbox: Sandbox, report: dict[str, Any]) -> None:
    built = await sandbox.exec(["find", ".", "-name", "bin", "-o", "-name", "obj"])
    staged = await sandbox.exec(["ls", "-A", sandbox.staging_dir])

    assert built.stdout == ""
    assert staged.stdout == ""


async def test_a_path_lints_only_its_part(sandbox: Sandbox) -> None:
    report = await _lint(sandbox, path="warnings", linters=["dotnet"])

    assert [(c["path"], c["status"]) for c in report["checks"]] == [("warnings", "ran")]
    assert {f["path"] for f in report["findings"]} == {"warnings/Calc.cs"}


async def test_without_a_proxy_dotnet_is_skipped_with_the_reason(
    client: docker.DockerClient, tmp_path: Path
) -> None:
    repos = tmp_path / "repos"
    make_repo(repos / "dotnet", {"clean/Clean.csproj": _project(), "clean/Ok.cs": "class Ok {}\n"})
    manager = DockerSandboxManager(client, local_root=repos)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "dotnet"))) as box:
        report = await _lint(box, linters=["dotnet"])

    (check,) = report["checks"]
    assert (check["status"], check["reason"]) == ("skipped", "NuGet restore is not configured")
