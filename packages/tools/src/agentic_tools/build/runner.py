"""Restores and builds the repo's Node and Python modules (13.2), the way `scan.lint` builds C#
(4.8): in job containers on the sandbox's files, never in the checkout.

For each module and ecosystem:

1. The module is copied, without `.git`, `node_modules`, `.venv`, `dist` and `build`, to a work
   directory under the staging directory, minus every file that names a package source or runs
   code (`workdir`).
2. A restore job on the registry's network (`npm` or `pypi`, through its egress proxy) downloads
   what the lockfile pins into a per-run cache, running no code of the repo (`commands`).
3. A build job with no network rebuilds what needs it, runs the module's `build` script (Node)
   or installs its own package (Python), from that cache.
4. The work directory is removed. The caches stay, so later jobs install offline from them.

Failures are fixed reasons, never the package manager's words (they may quote repo content).
"""

import posixpath
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import uuid4

from agentic_sandbox import Sandbox, SandboxError
from agentic_tools.build import commands
from agentic_tools.build.report import MAX_MODULES, BuildCheck, BuildReport, Ecosystem, build_report
from agentic_tools.build.stack import (
    CONFINE_FAILED,
    DESCRIBE_SCRIPT,
    MANAGER_NAME,
    MANAGER_VERSIONS,
    Described,
    Plan,
    describe,
    plan,
)
from agentic_tools.build.tests import (
    DOES_NOT_BUILD,
    NO_TESTS,
    TestCheck,
    TestReport,
    job_script,
    make_report,
    no_runner,
    node_runner,
    parse_junit,
    parse_node_output,
    python_has_pytest,
    split_junit,
    tests_failed_reason,
)
from agentic_tools.build.tests import (
    TIMED_OUT as TEST_TIMED_OUT,
)
from agentic_tools.build.workdir import (
    COPY_SCRIPT,
    PLACE_SCRIPT,
    Refused,
    poetry_requirements,
    prune_pyproject,
    prune_yarnrc,
    safe_requirements,
)
from agentic_tools.repo.stack import MODULES_SCRIPT, find_modules

MAX_SCANNED = 100
"""The most modules looked at for something to restore."""

_REGISTRY_NAME = {"node": "npm", "python": "PyPI"}
_NETWORK = {"node": "npm", "python": "pypi"}


@dataclass(frozen=True)
class BuildLimits:
    """How long each step may take: copying the module, restoring, building, testing."""

    copy_timeout_s: float = 120.0
    restore_timeout_s: float = 300.0
    build_timeout_s: float = 600.0
    test_timeout_s: float = 600.0


def _under(path: str, directory: str) -> bool:
    return directory == "." or path == directory or path.startswith(f"{directory}/")


class _Restorer:
    def __init__(self, sandbox: Sandbox, limits: BuildLimits) -> None:
        self._sandbox = sandbox
        self._limits = limits
        self._testing = False
        self._pending: TestCheck | None = None
        self.tests: list[TestCheck] = []

    async def test_modules(self, target: str, ecosystems: tuple[Ecosystem, ...]) -> TestReport:
        """Restore and build each module, then run its tests; one `TestCheck` per module."""
        self._testing = True
        report = await self.modules(target, ecosystems)
        return make_report(self.tests, truncated=report.truncated)

    async def modules(self, target: str, ecosystems: tuple[Ecosystem, ...]) -> BuildReport:
        listing = await self._sandbox.exec(["sh", "-c", MODULES_SCRIPT, "modules"])
        if listing.exit_code != 0:
            raise _Failed("could not read the repository's modules")
        found = [m.path for m in find_modules(listing.stdout) if _under(m.path, target)]
        checks: list[BuildCheck] = []
        for module in found[:MAX_SCANNED]:
            described = await self._describe(module)
            for item in self._plans(described, ecosystems):
                if len(checks) == MAX_MODULES:
                    return build_report(checks, truncated=True)
                checks.append(await self._check(module, described, item))
        return build_report(checks)

    async def _describe(self, module: str) -> Described:
        marker = f"::{uuid4().hex}::"
        result = await self._sandbox.exec(["sh", "-c", DESCRIBE_SCRIPT, "describe", module, marker])
        if result.exit_code == CONFINE_FAILED:
            raise _Failed("a module is outside the repository")
        return describe(result.stdout, marker) if result.exit_code == 0 else Described({})

    @staticmethod
    def _plans(described: Described, ecosystems: tuple[Ecosystem, ...]) -> list[Plan]:
        converted: str | None = None
        refused: str | None = None
        if "poetry.lock" in described.files and "uv.lock" not in described.files:
            try:
                converted = poetry_requirements(described.files["poetry.lock"])
            except Refused as e:
                refused = str(e)
        plans = plan(described, ecosystems, converted)
        if refused:
            plans = [replace(p, fail=refused) if p.lockfile == "poetry.lock" else p for p in plans]
        return [_clean_requirements(p, described) for p in plans]

    async def _check(self, module: str, described: Described, item: Plan) -> BuildCheck:
        self._pending = None
        check = await self._build_check(module, described, item)
        if self._testing:
            self.tests.append(self._pending or _test_check_of(check, item))
        return check

    async def _build_check(self, module: str, described: Described, item: Plan) -> BuildCheck:
        check = BuildCheck(
            path=module,
            ecosystem=item.ecosystem,
            manager=MANAGER_NAME[item.manager] if item.manager else None,
            lockfile=item.lockfile,
            status="ran",
            version=self._version(item),
        )
        if item.skip:
            return check.model_copy(update={"status": "skipped", "reason": item.skip})
        if _NETWORK[item.ecosystem] not in self._sandbox.job_networks:
            name = _REGISTRY_NAME[item.ecosystem]
            reason = f"skipped: {name} restore is not configured"
            return check.model_copy(update={"status": "skipped", "reason": reason})
        if item.fail:
            return check.model_copy(update={"status": "failed", "reason": item.fail})
        work = posixpath.join(self._sandbox.staging_dir, f"build-{uuid4().hex}")
        try:
            return await self._run(check, module, described, item, work)
        finally:
            with suppress(SandboxError, ValueError):
                await self._sandbox.exec(["rm", "-rf", "--", work])

    @staticmethod
    def _version(item: Plan) -> str | None:
        return MANAGER_VERSIONS.get(item.manager) if item.manager else None

    async def _run(
        self, check: BuildCheck, module: str, described: Described, item: Plan, work: str
    ) -> BuildCheck:
        def failed(reason: str, **extra: int | None) -> BuildCheck:
            return check.model_copy(update={"status": "failed", "reason": reason, **extra})

        assert item.manager is not None
        copy = await self._sandbox.exec(
            ["sh", "-c", COPY_SCRIPT, "copy", work, module, item.manager],
            timeout_s=self._limits.copy_timeout_s,
        )
        if copy.exit_code != 0:
            return failed("could not copy the module for the build")
        try:
            await self._place_files(work, described, item)
        except (Refused, SandboxError, ValueError) as e:
            return failed(str(e) if isinstance(e, Refused) else "could not prepare the module")

        cwd = f"{work}/src"
        script, args = commands.restore_script(item)
        started = time.monotonic()
        restore = await self._sandbox.run_job(
            ["sh", "-c", script, "restore", *args],
            network=_NETWORK[item.ecosystem],  # pyright: ignore[reportArgumentType]
            cwd=cwd,
            timeout_s=self._limits.restore_timeout_s,
            env=commands.job_env(self._sandbox.staging_dir, work, item, online=True),
        )
        restore_ms = round((time.monotonic() - started) * 1000)
        if restore.exit_code != 0:
            reason = commands.restore_failure(
                item.ecosystem, restore.exit_code, f"{restore.stdout}\n{restore.stderr}"
            )
            return failed(reason, restore_ms=restore_ms)
        check = check.model_copy(
            update={"restore_ms": restore_ms, "packages": commands.packages_in(restore.stdout)}
        )

        build = commands.build_script(item)
        if build is None:
            return await self._maybe_test(check, module, described, item, work, built=None)
        started = time.monotonic()
        built = await self._sandbox.run_job(
            ["sh", "-c", build, "build"],
            network="none",
            cwd=cwd,
            timeout_s=self._limits.build_timeout_s,
            env=commands.job_env(self._sandbox.staging_dir, work, item, online=False),
        )
        build_ms = round((time.monotonic() - started) * 1000)
        if built.exit_code == commands.TIMED_OUT:
            return failed("build timed out", build_ms=build_ms)
        if built.exit_code != 0:
            return failed(f"build failed (exit {built.exit_code})", build_ms=build_ms)
        check = check.model_copy(update={"build_ms": build_ms})
        return await self._maybe_test(check, module, described, item, work, built="ran")

    async def _maybe_test(
        self,
        check: BuildCheck,
        module: str,
        described: Described,
        item: Plan,
        work: str,
        *,
        built: Literal["ran"] | None,
    ) -> BuildCheck:
        if self._testing:
            self._pending = await self._test(module, described, item, work, built)
        return check

    async def _test(
        self, module: str, described: Described, item: Plan, work: str, built: Literal["ran"] | None
    ) -> TestCheck:
        """Run the module's tests in the work copy, in a job with no network."""
        base = TestCheck(path=module, ecosystem=item.ecosystem, status="skipped", build=built)
        runner: str | None
        if item.ecosystem == "node":
            _, runner = node_runner(described.files.get("package.json", ""))
            if runner is None:
                return base.model_copy(update={"reason": NO_TESTS})
        else:
            if not python_has_pytest(dict(described.files)):
                return base.model_copy(update={"reason": no_runner("python")})
            runner = "pytest"
        base = base.model_copy(update={"runner": runner})
        started = time.monotonic()
        job = await self._sandbox.run_job(
            ["sh", "-c", job_script(item), "test"],
            network="none",
            cwd=f"{work}/src",
            timeout_s=self._limits.test_timeout_s,
            env=commands.job_env(self._sandbox.staging_dir, work, item, online=False),
        )
        test_ms = round((time.monotonic() - started) * 1000)
        base = base.model_copy(update={"test_ms": test_ms})
        if job.exit_code == commands.TIMED_OUT:
            return base.model_copy(update={"status": "error", "reason": TEST_TIMED_OUT})
        if item.ecosystem == "python":
            _, junit = split_junit(job.stdout)
            outcome = parse_junit(junit)
            crashed = job.exit_code in (2, 3, 4)
            empty = job.exit_code == 5
        else:
            outcome = parse_node_output(runner, job.stdout + "\n" + job.stderr)
            crashed = False
            empty = job.exit_code == 0 and outcome is not None and outcome.total == 0
        counts: dict[str, Any] = {}
        if outcome is not None:
            counts = {
                "passed": outcome.passed,
                "failed": outcome.failed,
                "skipped": outcome.skipped,
                "failures": outcome.failures,
            }
        if empty:
            return base.model_copy(update={"reason": NO_TESTS})
        if crashed:
            return base.model_copy(update={"status": "error", "reason": "test run failed"})
        if job.exit_code == 0:
            return base.model_copy(update={"status": "passed", **counts})
        reason = tests_failed_reason(outcome)
        return base.model_copy(update={"status": "failed", "reason": reason, **counts})

    async def _place_files(self, work: str, described: Described, item: Plan) -> None:
        """Put the files the work copy gets in place of the repo's: the pruned configs and the
        requirements."""
        files: dict[str, str] = {}
        yarnrc = described.files.get(".yarnrc.yml")
        if yarnrc is not None:
            files[".yarnrc.yml"] = prune_yarnrc(yarnrc)
        pyproject = described.files.get("pyproject.toml")
        if pyproject is not None and (pruned := prune_pyproject(pyproject)) is not None:
            files["pyproject.toml"] = pruned
        if item.requirements and item.generated is not None:
            files[item.requirements] = item.generated
        for name, text in files.items():
            staged = await self._sandbox.put_file(text.encode())
            placed = await self._sandbox.exec(
                ["sh", "-c", PLACE_SCRIPT, "place", staged, work, name]
            )
            if placed.exit_code != 0:
                raise SandboxError("could not place a file")


def _clean_requirements(item: Plan, described: Described) -> Plan:
    """A requirements file from the repo, read for what it asks of the network; the generated
    ones are made by us from a lockfile or the module's own dependencies, and read too."""
    if item.ecosystem != "python" or item.skip or item.fail:
        return item
    text = item.generated
    if text is None and item.requirements:
        text = described.files.get(item.requirements)
    if text is None:
        return item
    try:
        return replace(item, generated=safe_requirements(text) if not item.hashes else text)
    except Refused as e:
        return replace(item, fail=str(e))


def _test_check_of(check: BuildCheck, item: Plan) -> TestCheck:
    """The test check for a module whose restore or build did not get as far as the tests."""
    base = TestCheck(path=check.path, ecosystem=item.ecosystem, status="skipped")
    reason = check.reason or ""
    if check.status == "skipped":
        return base.model_copy(update={"reason": reason})
    if reason.startswith("build "):
        return base.model_copy(
            update={"status": "failed", "reason": DOES_NOT_BUILD, "build": "failed"}
        )
    return base.model_copy(update={"status": "error", "reason": reason or "could not run"})


class _Failed(Exception):
    """The call cannot be answered; the message is safe to show."""


async def restore_modules(
    sandbox: Sandbox,
    target: str = ".",
    ecosystems: Sequence[Ecosystem] = ("node", "python"),
    limits: BuildLimits | None = None,
) -> BuildReport:
    """Restore and build the Node and Python modules at or under `target` (a repo-relative path
    already checked). Raises `RuntimeError` with a safe message when the repo cannot be read."""
    try:
        return await _Restorer(sandbox, limits or BuildLimits()).modules(
            target, tuple(dict.fromkeys(ecosystems))
        )
    except _Failed as e:
        raise RuntimeError(str(e)) from None


async def test_modules(
    sandbox: Sandbox,
    target: str = ".",
    ecosystems: Sequence[Ecosystem] = ("node", "python"),
    limits: BuildLimits | None = None,
) -> TestReport:
    """Restore, build and test the Node and Python modules at or under `target`. Raises
    `RuntimeError` with a safe message when the repo cannot be read."""
    try:
        return await _Restorer(sandbox, limits or BuildLimits()).test_modules(
            target, tuple(dict.fromkeys(ecosystems))
        )
    except _Failed as e:
        raise RuntimeError(str(e)) from None


test_modules.__test__ = False  # type: ignore[attr-defined]  # not a pytest test
