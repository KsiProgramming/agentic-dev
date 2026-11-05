"""`scan.lint`'s .NET engine on a scripted sandbox (4.8): SARIF logs in, checks and findings out,
and every way a restore or build fails turned into a short, fixed reason. The real build runs in
`test_scan_dotnet_docker.py`."""

import io
import json
import tarfile
from collections.abc import Mapping, Sequence
from typing import Any

from agentic_sandbox import ExecResult, JobNetwork
from agentic_tools.scan.dotnet import (
    RESTORE_NOT_CONFIGURED,
    error_reason,
    lint_dotnet,
    msbuild_errors,
)
from agentic_tools.scan.normalise import sarif_findings
from agentic_tools.scan.report import ConfigSource
from agentic_tools.scan.stack import LintTarget

STAGING = "/workspace/.incoming"


def _sarif(*results: dict[str, Any], rules: Sequence[dict[str, Any]] = ()) -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "csc", "rules": list(rules)}},
                    "results": list(results),
                }
            ],
        }
    )


def _result(
    rule: str,
    uri: str | None,
    line: int = 1,
    level: str = "warning",
    message: str = "a diagnostic",
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {"ruleId": rule, "level": level, "message": {"text": message}, **extra}
    if uri is not None:
        result["locations"] = [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": line, "endLine": line + 1},
                }
            }
        ]
    return result


# SARIF reading.

ROOT = f"{STAGING}/dotnet-x/repo"


def test_sarif_findings_keep_what_the_repo_should_see() -> None:
    raw = _sarif(
        _result("CA1822", f"file://{ROOT}/src/Api/Calc.cs", 5, message="Mark it static"),
        _result("CA1805", f"file://{ROOT}/src/Api/Calc.cs", 8, level="note"),
        _result("CA2201", f"file://{ROOT}/src/Api/My%20File.cs", 3, level="error"),
        rules=[{"id": "CA1822", "helpUri": "https://learn.microsoft.com/ca1822"}],
    )

    read = sarif_findings(raw, root=ROOT, config="repo")

    assert [(f.rule, f.path, f.line, f.end_line, f.severity) for f in read.findings] == [
        ("CA1822", "src/Api/Calc.cs", 5, 6, "low"),
        ("CA1805", "src/Api/Calc.cs", 8, 9, "info"),
        ("CA2201", "src/Api/My File.cs", 3, 4, "medium"),
    ]
    first = read.findings[0]
    assert (first.tool, first.category, first.config) == ("dotnet", "lint", "repo")
    assert first.message == "Mark it static"
    assert first.help_url == "https://learn.microsoft.com/ca1822"
    assert first.fingerprint
    assert read.compile_errors == []


def test_sarif_findings_drop_what_is_not_the_repos() -> None:
    raw = _sarif(
        _result("CA1822", f"file://{ROOT}/a.cs", suppressions=[{"kind": "inSource"}]),
        _result("IDE0005", f"file://{ROOT}/a.cs", level="none"),
        _result("SA0001", None),
        _result("CA1050", f"file://{ROOT}/src/obj/Debug/net10.0/Gen.g.cs"),
        _result("CA1050", "file:///usr/share/dotnet/sdk/Shared.cs"),
        _result("CA1050", f"file://{ROOT}/../escape.cs"),
    )

    assert sarif_findings(raw, root=ROOT, config="platform-default").findings == []


def test_compiler_errors_are_counted_not_reported() -> None:
    raw = _sarif(
        _result("CS0103", f"file://{ROOT}/src/C.cs", level="error"),
        _result("CS8019", f"file://{ROOT}/src/C.cs", level="note"),
    )

    read = sarif_findings(raw, root=ROOT, config="repo")

    assert read.compile_errors == ["src/C.cs"]
    assert [f.rule for f in read.findings] == ["CS8019"]


# MSBuild's error lines.


def test_error_reasons_are_short_and_fixed() -> None:
    assert error_reason("NU1101") == "restore failed: a package is not on nuget.org"
    assert error_reason("NU1301") == "restore failed: a package source is not reachable"
    assert error_reason("NU1605") == "restore failed: NU1605"
    assert error_reason("MSB4019") == "build failed: MSB4019"
    assert error_reason("NETSDK1045") == "needs a newer .NET SDK"
    text = (
        " To build this project, the following workloads must be installed: maui-android maui-ios"
    )
    assert error_reason("NETSDK1147", text) == "needs the maui-android and maui-ios workload"
    assert error_reason("NETSDK1147", "<script>") == "needs a workload"


def test_msbuild_errors_name_their_project() -> None:
    output = (
        "/w/repo/feed/Feed.csproj : error NU1101: Unable to find package X. [/w/scan.sln]\n"
        "/usr/share/dotnet/sdk/x.targets(266,5): error NETSDK1004: Assets file missing. "
        "[/w/repo/broken/Broken.csproj]\n"
        "/w/repo/broken/C.cs(1,49): error CS0103: The name 'Missing' does not exist "
        "[/w/repo/b.csproj]\n"
        "/usr/share/dotnet/sdk/NuGet.targets(782,5): error : NuGet.Config is not valid XML. "
        "[/w/repo/a/A.csproj]\n"
        "/w/repo/a/A.cs(3,1): warning CA1822: not an error [/w/repo/a/A.csproj]\n"
    )

    assert msbuild_errors(output, "restore") == [
        ("/w/repo/feed/Feed.csproj", "restore failed: a package is not on nuget.org"),
        ("/w/repo/broken/Broken.csproj", "build failed: NETSDK1004"),
        ("/w/repo/a/A.csproj", "restore failed"),
    ]


# The engine, on a scripted sandbox.


def _tar(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"./{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class DotnetSandbox:
    """Answers the .NET engine's steps: the copy, the restore and build jobs (scripted results),
    and the logs the build wrote (`logs`: (project path in the repo, SARIF text) pairs)."""

    workdir = "/workspace/repo"
    staging_dir = STAGING

    def __init__(
        self,
        logs: Sequence[tuple[str, str]] = (),
        *,
        restore: ExecResult | None = None,
        build: ExecResult | None = None,
        prep_exit: int = 0,
        networks: frozenset[JobNetwork] = frozenset({"none", "nuget"}),
    ) -> None:
        self.logs = logs
        self.restore = restore or ExecResult(0, "", "")
        self.build = build or ExecResult(0, "", "")
        self.prep_exit = prep_exit
        self.job_networks = networks
        self.work = ""
        self.jobs: list[tuple[str, list[str], Mapping[str, str]]] = []
        self.removed: list[str] = []
        self.files: dict[str, bytes] = {}

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = 30.0, cwd: str | None = None
    ) -> ExecResult:
        if argv[0] == "rm":
            self.removed.append(argv[-1])
            return ExecResult(0, "", "")
        step = argv[3]
        if step == "prep":
            self.work = argv[4]
            self.modules = list(argv[5:])
            return ExecResult(self.prep_exit, "", "")
        assert step == "collect"
        files: dict[str, bytes] = {}
        for i, (project, sarif) in enumerate(self.logs):
            files[f"log-{i}.sarif"] = sarif.replace("ROOT", f"{self.work}/repo").encode()
            files[f"log-{i}.project"] = f"{self.work}/repo/{project}\n".encode()
        self.files[argv[5]] = _tar(files)
        return ExecResult(0, "", "")

    async def run_job(
        self,
        argv: Sequence[str],
        *,
        network: JobNetwork,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        assert cwd == self.work
        self.jobs.append((network, list(argv), dict(env or {})))
        result = self.restore if network == "nuget" else self.build
        return ExecResult(result.exit_code, result.stdout.replace("WORK", self.work), result.stderr)

    async def take_file(self, path: str) -> bytes:
        return self.files.pop(path)


def _target(module: str, config: ConfigSource = "platform-default") -> LintTarget:
    return LintTarget("dotnet", module, module, "dotnet", config)


async def _lint(sandbox: DotnetSandbox, *targets: LintTarget) -> tuple[list[Any], list[Any]]:
    checks, findings = await lint_dotnet(sandbox, list(targets), version="10.0.403")  # type: ignore[arg-type]
    return [(c.path, c.status, c.reason, c.findings) for c in checks], findings


async def test_each_module_gets_its_findings_from_its_projects_logs() -> None:
    sandbox = DotnetSandbox(
        [
            (
                "src/Api/Api.csproj",
                _sarif(
                    _result("CA1822", "file://ROOT/src/Api/Calc.cs", 5),
                    _result("CA2201", "file://ROOT/src/Api/Calc.cs", 7),
                ),
            ),
            # Two target frameworks: the same finding in two logs.
            ("src/Core/Core.csproj", _sarif(_result("SA1200", "file://ROOT/src/Core/A.cs"))),
            ("src/Core/Core.csproj", _sarif(_result("SA1200", "file://ROOT/src/Core/A.cs"))),
        ]
    )

    checks, findings = await _lint(sandbox, _target("src/Api", "repo"), _target("src/Core"))

    assert checks == [("src/Api", "ran", None, 2), ("src/Core", "ran", None, 1)]
    assert sorted((f.path, f.rule, f.config) for f in findings) == [
        ("src/Api/Calc.cs", "CA1822", "repo"),
        ("src/Api/Calc.cs", "CA2201", "repo"),
        ("src/Core/A.cs", "SA1200", "platform-default"),
    ]
    assert sandbox.modules == ["src/Api", "src/Core"]
    assert sandbox.removed == [sandbox.work]


async def test_the_restore_reaches_nuget_and_the_build_nothing() -> None:
    sandbox = DotnetSandbox([("a/A.csproj", _sarif())])

    await _lint(sandbox, _target("a"))

    (restore_network, restore, env), (build_network, build, _) = sandbox.jobs
    assert restore_network == "nuget"
    assert "/opt/scan/dotnet/nuget.config" in restore[2]
    assert build_network == "none"
    assert build[:3] == ["dotnet", "build", "scan.sln"]
    assert "--no-restore" in build
    assert "-p:CustomAfterMicrosoftCommonTargets=/opt/scan/dotnet/scan.targets" in build
    assert env["NUGET_PACKAGES"].startswith(f"{STAGING}/dotnet-")


async def test_restore_and_build_failures_are_reasons_on_their_modules() -> None:
    sandbox = DotnetSandbox(
        [
            ("ok/Ok.csproj", _sarif(_result("CA1822", "file://ROOT/ok/A.cs"))),
            (
                "broken/Broken.csproj",
                _sarif(
                    _result("CS0103", "file://ROOT/broken/C.cs", level="error"),
                    _result("CS0246", "file://ROOT/broken/C.cs", 2, level="error"),
                    _result("CA1822", "file://ROOT/broken/C.cs"),
                ),
            ),
        ],
        restore=ExecResult(
            1,
            # As NuGet writes it: the project, then the solution in brackets.
            "WORK/repo/feed/Feed.csproj : error NU1101: Unable to find package Contoso. "
            "[WORK/scan.sln]\n",
            "",
        ),
        build=ExecResult(
            1,
            "x.targets(1,1): error NETSDK1004: Assets file not found. "
            "[WORK/repo/feed/Feed.csproj]\n"
            "x.targets(1,1): error NETSDK1147: To build this project, the following workloads "
            "must be installed: maui-android [WORK/repo/app/App.csproj]\n",
            "",
        ),
    )

    checks, findings = await _lint(
        sandbox, _target("ok"), _target("broken"), _target("feed"), _target("app")
    )

    assert checks == [
        ("ok", "ran", None, 1),
        ("broken", "failed", "does not compile (2 errors)", 0),
        ("feed", "failed", "restore failed: a package is not on nuget.org", 0),
        ("app", "failed", "needs the maui-android workload", 0),
    ]
    assert [f.path for f in findings] == ["ok/A.cs"]


async def test_a_step_that_times_out_fails_every_module() -> None:
    for restore, build, reason in (
        (ExecResult(124, "", "timed out"), None, "restore timed out"),
        (None, ExecResult(124, "", "timed out"), "build timed out"),
    ):
        sandbox = DotnetSandbox(restore=restore, build=build)

        checks, _ = await _lint(sandbox, _target("a"), _target("b"))

        assert checks == [("a", "failed", reason, 0), ("b", "failed", reason, 0)]
        assert sandbox.removed == [sandbox.work]


async def test_a_restore_that_fails_with_no_error_line_fails_every_module() -> None:
    sandbox = DotnetSandbox(restore=ExecResult(1, "Something went wrong.\n", ""))

    checks, _ = await _lint(sandbox, _target("a"))

    assert checks == [("a", "failed", "restore failed", 0)]
    assert len(sandbox.jobs) == 1


async def test_a_module_whose_build_wrote_no_log_says_so() -> None:
    sandbox = DotnetSandbox([("a/A.csproj", _sarif())])

    checks, _ = await _lint(sandbox, _target("a"), _target("b"))

    assert checks == [
        ("a", "ran", None, 0),
        ("b", "failed", "the build wrote no analyzer log", 0),
    ]


async def test_findings_outside_the_path_asked_for_are_left_out() -> None:
    sandbox = DotnetSandbox(
        [
            (
                "api/Api.csproj",
                _sarif(
                    _result("CA1822", "file://ROOT/api/Services/S.cs"),
                    _result("CA1822", "file://ROOT/api/Other.cs"),
                ),
            )
        ]
    )

    checks, findings = await lint_dotnet(
        sandbox,  # type: ignore[arg-type]
        [LintTarget("dotnet", "api", "api/Services", "dotnet", "repo")],
        version=None,
    )

    assert [(c.path, c.findings) for c in checks] == [("api/Services", 1)]
    assert [f.path for f in findings] == ["api/Services/S.cs"]


async def test_no_copy_no_build() -> None:
    for exit_code, reason in (
        (3, "no C# project found"),
        (1, "could not copy the repo for the build"),
    ):
        sandbox = DotnetSandbox(prep_exit=exit_code)

        checks, _ = await _lint(sandbox, _target("a"))

        assert checks == [("a", "failed", reason, 0)]
        assert sandbox.jobs == []


async def test_without_a_nuget_proxy_dotnet_is_skipped() -> None:
    sandbox = DotnetSandbox(networks=frozenset({"none"}))

    checks, findings = await _lint(sandbox, _target("a"))

    assert checks == [("a", "skipped", RESTORE_NOT_CONFIGURED, 0)]
    assert findings == []
    assert sandbox.jobs == []
