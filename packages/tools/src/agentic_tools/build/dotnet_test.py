"""`build.test` for .NET (13.3): restore the C# projects, then build and test them with no network,
the way `scan.lint`'s .NET engine builds them (4.8), and read the TRX files `dotnet test` writes.

1. `PREP_SCRIPT` copies the repo, without `.git`, `bin/`, `obj/` and `node_modules`, to a work
   directory under the staging directory and lists the C# projects under the target.
2. A restore job (network `nuget`) makes one solution of them and restores it with the platform's
   `nuget.config`: the repo's own package sources are never read, and no repo code runs while the
   network is up.
3. A test job (network `none`) runs `dotnet test` on the solution with no restore. It builds, so
   a project that does not compile ends it without TRX files (`does not build`), and prints each
   project's TRX after a marker.

One check covers the target: a solution's projects build and test together. Failures are fixed
reasons, never the tool's words (they may quote repo content).
"""

import posixpath
import re
import time
from contextlib import suppress
from uuid import uuid4

from agentic_sandbox import Sandbox, SandboxError
from agentic_tools.build.changed import changed_coverage, parse_cobertura
from agentic_tools.build.tests import (
    BASE_DID_NOT_BUILD,
    COVERAGE_FAILED,
    DOES_NOT_BUILD,
    MAX_CASES,
    NO_TESTS,
    TIMED_OUT,
    TRX_MARKER,
    Outcome,
    TestCheck,
    TestOptions,
    build_errors,
    parse_trx,
    split_trx,
    tests_failed_reason,
)
from agentic_tools.scan.dotnet import (
    PREP_SCRIPT,
    RESTORE_NOT_CONFIGURED,
    RESTORE_SCRIPT,
    DotnetLimits,
    msbuild_errors,
)

_NO_PROJECTS = 3
_SLN_FAILED = 4
_JOB_TIMED_OUT = 124

# In the test job, from the work directory: test every test project of the solution with no
# restore, writing one TRX per project, and print them after the marker.
TEST_SCRIPT = f"""
dotnet test scan.sln --no-restore -nologo -v:q -tl:off -clp:NoSummary --disable-build-servers \\
  -nodeReuse:false --logger trx --results-directory "$PWD/out/trx"
code=$?
echo "{TRX_MARKER}"
for f in out/trx/*.trx; do [ -f "$f" ] && cat "$f"; done
exit $code
"""

COBERTURA_MARKER = "::cobertura::"

# With options (13.4): `$@` holds criterion ids, which narrow the run on the base to the tests that
# name them (`--filter`), and coverage is collected by the SDK's own collector as Cobertura, printed
# before the TRX files after its marker.
_DOTNET_FILTER = """
filter=""
for id in "$@"; do
  n=${id#AC-}
  for v in "AC$n" "AC_$n" "ac$n" "ac_$n"; do filter="${filter:+$filter|}FullyQualifiedName~$v"; done
done
if [ -n "$filter" ]; then set -- --filter "$filter"; else set --; fi
"""


def test_script(options: TestOptions | None = None) -> str:
    """The test job's script: `TEST_SCRIPT`, or with `options` a run of only the tests that name
    the ids in `$@` (on the base) and/or one that collects coverage."""
    options = options or TestOptions()
    if not options.base and not options.coverage:
        return TEST_SCRIPT
    collect = ' --collect "Code Coverage;Format=cobertura"' if options.coverage else ""
    return (
        (_DOTNET_FILTER if options.base else "set --\n")
        + "dotnet test scan.sln --no-restore -nologo -v:q -tl:off -clp:NoSummary "
        "--disable-build-servers -nodeReuse:false --logger trx "
        f'--results-directory "$PWD/out/trx"{collect} "$@"\ncode=$?\n'
        f'echo "{COBERTURA_MARKER}"\n'
        "for f in $(find out/trx -name '*.cobertura.xml' 2>/dev/null); do cat \"$f\"; done\n"
        f'echo "{TRX_MARKER}"\n'
        'for f in out/trx/*.trx; do [ -f "$f" ] && cat "$f"; done\n'
        "exit $code\n"
    )


def split_cobertura(output: str) -> list[str]:
    """The Cobertura documents a coverage job printed before the TRX marker."""
    _, found, tail = output.partition(f"{COBERTURA_MARKER}\n")
    if not found:
        return []
    tail = tail.replace("\ufeff", "")
    return [f"<?xml{part}" for part in tail.split("<?xml") if part.strip()]


# Any build error but a restore (`NU…`) or an MSBuild one (`MSB…`): the compiler's (`CS…`) and the
# repo's analyzers', which a repo may raise to errors (`S4144`, `CA2201`, `IDE0005`).
_COMPILE_ERROR = re.compile(r"\berror\s+(?!NU\d|MSB\d)[A-Za-z]{1,6}\d{1,5}\b")


async def test_dotnet(
    sandbox: Sandbox,
    target: str,
    limits: DotnetLimits,
    test_timeout_s: float,
    options: TestOptions | None = None,
) -> TestCheck | None:
    """The check for the C# projects at or under `target`, or None when there are none."""
    base = TestCheck(path=target, ecosystem="dotnet", runner="dotnet test", status="skipped")
    if "nuget" not in sandbox.job_networks:
        return base.model_copy(update={"runner": None, "reason": RESTORE_NOT_CONFIGURED})
    work = posixpath.join(sandbox.staging_dir, f"dotnet-test-{uuid4().hex}")
    try:
        return await _run(sandbox, base, target, work, limits, test_timeout_s, options)
    finally:
        with suppress(SandboxError, ValueError):
            await sandbox.exec(["rm", "-rf", "--", work])


async def _run(
    sandbox: Sandbox,
    base: TestCheck,
    target: str,
    work: str,
    limits: DotnetLimits,
    test_timeout_s: float,
    options: TestOptions | None = None,
) -> TestCheck | None:
    options = options or TestOptions()

    def error(reason: str) -> TestCheck:
        return base.model_copy(update={"status": "error", "reason": reason})

    prep = await sandbox.exec(
        # The script's `find` prunes a start path named `.`, so the repo root is an empty module.
        ["sh", "-c", PREP_SCRIPT, "prep", work, "" if target == "." else target],
        timeout_s=limits.prep_timeout_s,
    )
    if prep.exit_code == _NO_PROJECTS:
        return None
    if prep.exit_code != 0:
        return error("could not copy the repo for the build")
    home = f"{work}/home"
    env = {
        "HOME": home,
        "DOTNET_CLI_HOME": home,
        "NUGET_PACKAGES": f"{work}/nuget",
        "DOTNET_NOLOGO": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        # The image has one runtime (the SDK's); tests built for an older one run on it.
        "DOTNET_ROLL_FORWARD": "LatestMajor",
    }
    restore = await sandbox.run_job(
        ["sh", "-c", RESTORE_SCRIPT, "restore"],
        network="nuget",
        cwd=work,
        timeout_s=limits.restore_timeout_s,
        env=env,
    )
    if restore.exit_code == _JOB_TIMED_OUT:
        return error("restore timed out")
    if restore.exit_code == _SLN_FAILED:
        return error("could not load the projects")
    restore_errors = msbuild_errors(restore.stdout, "restore")
    if restore.exit_code != 0:
        return error(restore_errors[0][1] if restore_errors else "restore failed")

    started = time.monotonic()
    job = await sandbox.run_job(
        ["sh", "-c", test_script(options), "test", *(options.select if options.base else ())],
        network="none",
        cwd=work,
        timeout_s=test_timeout_s,
        env=env,
    )
    test_ms = round((time.monotonic() - started) * 1000)
    base = base.model_copy(update={"test_ms": test_ms})
    if job.exit_code == _JOB_TIMED_OUT:
        return base.model_copy(update={"status": "error", "reason": TIMED_OUT})
    output, documents = split_trx(job.stdout)
    outcome = parse_trx(documents)
    extra = _extras(options, output, outcome)
    if outcome is None:
        if job.exit_code == 0:
            return base.model_copy(update={"reason": NO_TESTS, "build": "ran"})
        if _COMPILE_ERROR.search(f"{output}\n{job.stderr}"):
            reason = BASE_DID_NOT_BUILD if options.base else DOES_NOT_BUILD
            errors = build_errors(f"{output}\n{job.stdout}\n{job.stderr}")
            return base.model_copy(
                update={
                    "status": "failed",
                    "reason": reason,
                    "build": "failed",
                    "build_errors": errors,
                }
            )
        return base.model_copy(update={"status": "error", "reason": "test run failed"})
    counts = {
        "passed": outcome.passed,
        "failed": outcome.failed,
        "skipped": outcome.skipped,
        "failures": outcome.failures,
        "build": "ran",
        **extra,
    }
    if outcome.total == 0 and job.exit_code != 0:  # the test host could not start
        return base.model_copy(update={"status": "error", "reason": "test run failed"})
    if outcome.total == 0:
        return base.model_copy(update={"reason": NO_TESTS, "build": "ran"})
    if job.exit_code == 0 and not outcome.failed:
        return base.model_copy(update={"status": "passed", **counts})
    if outcome.failed:
        reason = tests_failed_reason(outcome)
        return base.model_copy(update={"status": "failed", "reason": reason, **counts})
    return base.model_copy(update={"status": "error", "reason": "test run failed", **counts})


def _extras(options: TestOptions, output: str, outcome: Outcome | None) -> dict[str, object]:
    """The `cases` and `coverage` the job was asked for."""
    extra: dict[str, object] = {}
    if options.select and outcome is not None:
        wanted = set(options.select)
        extra["cases"] = [c for c in outcome.cases if wanted & set(c.ids)][:MAX_CASES]
    if options.coverage and not options.base:
        reports = [r for r in map(parse_cobertura, split_cobertura(output)) if r is not None]
        if not reports:
            extra["coverage_reason"] = COVERAGE_FAILED
        else:
            merged: dict[str, tuple[set[int], set[int]]] = {}
            for report in reports:
                for name, (executable, ran) in report.items():
                    have = merged.setdefault(name, (set(), set()))
                    have[0].update(executable)
                    have[1].update(ran)
            extra["coverage"] = changed_coverage(options.changes, merged)
    return extra
