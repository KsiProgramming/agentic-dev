# ruff: noqa: E501
"""`build.test` for .NET (13.3) on a scripted sandbox: the restore on the NuGet network, the test job
on `none`, TRX files read into counts and capped failures, and every outcome turned into a fixed
reason. The real jobs need the .NET image and the NuGet proxy."""

from collections.abc import Mapping, Sequence

from agentic_sandbox import ExecResult, JobNetwork
from agentic_tools.build import BuildLimits
from agentic_tools.build.runner import test_modules as run_tests
from agentic_tools.build.tests import TRX_MARKER, parse_trx, split_trx

STAGING = "/workspace/.incoming"
NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"


def trx(*results: tuple[str, str, str]) -> str:
    """A TRX document: each result is (test name, outcome, failure message)."""
    units = "".join(
        f'<UnitTest id="{i}"><TestMethod className="Shop.Tests.CartTests" name="{n}"/></UnitTest>'
        for i, (n, _, _) in enumerate(results)
    )
    rows = "".join(
        f'<UnitTestResult testId="{i}" testName="{n}" outcome="{o}">'
        + (f"<Output><ErrorInfo><Message>{m}</Message></ErrorInfo></Output>" if m else "")
        + "</UnitTestResult>"
        for i, (n, o, m) in enumerate(results)
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?><TestRun xmlns="{NS}">'
        f"<Results>{rows}</Results><TestDefinitions>{units}</TestDefinitions></TestRun>"
    )


PASSING = trx(("Adds", "Passed", ""), ("Removes", "Passed", ""))
FAILING = trx(("Adds", "Passed", ""), ("Totals", "Failed", "Assert.Equal() Failure: 4 vs 3"))


class DotnetSandbox:
    """Answers the prep, the restore job and the test job."""

    workdir = "/workspace/repo"
    staging_dir = STAGING

    def __init__(
        self,
        *,
        prep: int = 0,
        restore: ExecResult | None = None,
        tested: ExecResult | None = None,
        networks: frozenset[JobNetwork] = frozenset({"none", "nuget"}),
    ) -> None:
        self.prep = prep
        self.restore = restore or ExecResult(0, "", "")
        self.tested = tested or ExecResult(0, f"{TRX_MARKER}\n{PASSING}", "")
        self.job_networks = networks
        self.jobs: list[tuple[JobNetwork, str]] = []
        self.removed: list[str] = []

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = 30.0, cwd: str | None = None
    ) -> ExecResult:
        if argv[0] == "rm":
            self.removed.append(argv[-1])
            return ExecResult(0, "", "")
        if argv[3] == "modules":  # node and python modules: none here
            return ExecResult(0, "::dirs::\n", "")
        if argv[3] == "describe":  # a module with no manifest or lockfile
            return ExecResult(0, "", "")
        assert argv[3] == "prep", argv
        return ExecResult(self.prep, "", "")

    async def run_job(
        self,
        argv: Sequence[str],
        *,
        network: JobNetwork,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        assert cwd.startswith(f"{STAGING}/dotnet-test-")
        self.jobs.append((network, argv[2]))
        return self.restore if network == "nuget" else self.tested


async def dotnet(box: DotnetSandbox) -> list[tuple[str, str | None, str | None]]:
    report = await run_tests(box, ".", ("dotnet",), BuildLimits())  # type: ignore[arg-type]
    return [(c.status, c.reason, c.build) for c in report.checks]


async def test_a_passing_solution_restores_on_nuget_and_tests_with_no_network() -> None:
    box = DotnetSandbox()

    report = await run_tests(box, ".", ("dotnet",))  # type: ignore[arg-type]

    [check] = report.checks
    assert (check.ecosystem, check.runner, check.status) == ("dotnet", "dotnet test", "passed")
    assert (check.passed, check.failed, check.build) == (2, 0, "ran")
    assert [network for network, _ in box.jobs] == ["nuget", "none"]  # tests run offline
    assert "dotnet test scan.sln --no-restore" in box.jobs[1][1]
    assert len(box.removed) == 1  # the work copy goes


async def test_a_failing_test_is_named_with_its_class_and_message() -> None:
    box = DotnetSandbox(tested=ExecResult(1, f"{TRX_MARKER}\n{FAILING}", ""))

    report = await run_tests(box, ".", ("dotnet",))  # type: ignore[arg-type]

    [check] = report.checks
    assert (check.status, check.reason) == ("failed", "tests failed (1 of 2)")
    [failure] = check.failures
    assert (failure.name, failure.file) == ("Totals", "Shop.Tests.CartTests")
    assert failure.message == "Assert.Equal() Failure: 4 vs 3"


async def test_a_project_that_does_not_compile_is_not_tested() -> None:
    box = DotnetSandbox(
        tested=ExecResult(1, "Cart.cs(3,1): error CS1002: ; expected [Core.csproj]\n", "")
    )

    assert await dotnet(box) == [("failed", "does not build", "failed")]


async def test_no_project_means_no_dotnet_check() -> None:
    box = DotnetSandbox(prep=3)

    report = await run_tests(box, ".", ("dotnet",))  # type: ignore[arg-type]

    assert report.checks == []
    assert box.jobs == []  # no job started


async def test_a_restore_that_fails_is_an_error_with_a_fixed_reason() -> None:
    box = DotnetSandbox(
        restore=ExecResult(1, "Core.csproj : error NU1101: Unable to find package Secret.Pkg", "")
    )

    assert await dotnet(box) == [("error", "restore failed: a package is not on nuget.org", None)]
    assert [network for network, _ in box.jobs] == ["nuget"]  # nothing was tested


async def test_a_solution_with_no_test_project_has_no_tests() -> None:
    box = DotnetSandbox(tested=ExecResult(0, f"{TRX_MARKER}\n", ""))

    assert await dotnet(box) == [("skipped", "no tests found", "ran")]


async def test_a_timeout_is_an_error_and_a_missing_proxy_is_skipped() -> None:
    slow = DotnetSandbox(tested=ExecResult(124, "", ""))
    offline = DotnetSandbox(networks=frozenset({"none"}))

    assert await dotnet(slow) == [("error", "test run timed out", None)]
    [(status, reason, _)] = await dotnet(offline)
    assert (status, reason) == ("skipped", "NuGet restore is not configured")
    assert offline.jobs == []


def test_trx_files_of_several_projects_are_added_up_and_capped() -> None:
    many = trx(*[(f"T{i}", "Failed", "x" * 900) for i in range(30)])
    _, documents = split_trx(f"out\n{TRX_MARKER}\n{PASSING}{many}")

    outcome = parse_trx(documents)

    assert outcome is not None
    assert (outcome.passed, outcome.failed) == (2, 30)
    assert len(outcome.failures) == 20  # capped, though all 30 are counted
    assert all(len(f.message or "") <= 500 for f in outcome.failures)


def test_a_trx_with_a_dtd_or_that_is_not_one_is_ignored() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><TestRun><Results/></TestRun>'

    assert parse_trx([bomb, "not xml", "<Other/>"]) is None


def test_the_byte_order_mark_dotnet_writes_does_not_break_the_documents() -> None:
    marked = chr(0xFEFF)
    _, documents = split_trx(
        "out" + chr(10) + TRX_MARKER + chr(10) + marked + PASSING + marked + FAILING
    )

    outcome = parse_trx(documents)

    assert len(documents) == 2
    assert outcome is not None and (outcome.passed, outcome.failed) == (3, 1)


async def test_a_test_host_that_cannot_start_is_a_failed_run_not_no_tests() -> None:
    empty = trx()
    box = DotnetSandbox(tested=ExecResult(1, TRX_MARKER + chr(10) + empty, ""))

    assert await dotnet(box) == [("error", "test run failed", None)]
