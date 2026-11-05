"""`scan.lint`'s .NET engine (4.8): the Roslyn analyzers of C# projects, run by a build.

Analyzers run on a compilation, so the projects are restored and built. Neither happens in the
checkout, nor in the run's sandbox container:

1. `PREP_SCRIPT` (in the sandbox) copies the repo, without `.git`, `bin/`, `obj/` and
   `node_modules`, to a work directory under the staging directory, and lists the C# projects of
   the modules to lint.
2. A restore job (`Sandbox.run_job`, network `nuget`) makes one solution of those projects and
   restores it with the platform's `nuget.config` (nuget.org only), through the egress proxy.
   The repo's own package sources are never read.
3. A build job (network `none`) builds the solution with no restore. `scan.targets` gives each
   project and target framework its own SARIF log, keeps warnings as warnings and records which
   project wrote which log.
4. The logs come back as one tar (`take_file`) and are read by `sarif_findings`; the work
   directory is removed.

Jobs run from the work directory, outside the repo's copy, so a `global.json` that pins an SDK
the image does not have does not stop the build: the SDK in the image builds it, and its
version is the check's `version`.

Each C# module is one check. Restore and build errors are read from MSBuild's error lines and
reported as short, fixed reasons, never the tool's words (they may quote repo content). A
module whose code does not compile is a failed check, without findings: analyzers on a broken
compilation report noise.
"""

import io
import posixpath
import re
import tarfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

from agentic_sandbox import Sandbox, SandboxError
from agentic_tools.scan.normalise import ScanOutputError, sarif_findings
from agentic_tools.scan.report import Check, Finding
from agentic_tools.scan.stack import LintTarget

DOTNET_CONFIG_DIR = "/opt/scan/dotnet"
"""The platform's .NET files in the sandbox image: `nuget.config` and `scan.targets`."""

MAX_PROJECTS = 500
"""The most C# projects one scan builds."""

RESTORE_NOT_CONFIGURED = "NuGet restore is not configured"
TIMED_OUT = 124

_NO_PROJECTS = 3
_SLN_FAILED = 4

# Copies the repo (the current directory) to `$1/repo` without VCS data, build output and
# dependencies, and lists the C# projects under the module directories `$2...` in `$1/projects`
# (paths in the copy). No user argument reaches the script: the directories are the probe's.
PREP_SCRIPT = f"""
work=$1; shift
mkdir -p "$work/repo" "$work/out" "$work/home" || exit 1
tar -cf - --exclude=.git --exclude=bin --exclude=obj --exclude=node_modules . \\
  | tar -C "$work/repo" -xf - || exit 1
for m in "$@"; do
  find "$work/repo/$m" \\( -type d \\( -name '.*' -o -name node_modules \\) -prune \\) \\
    -o -type f -name '*.csproj' -print
done | sort -u | head -n {MAX_PROJECTS} > "$work/projects" || exit 1
[ -s "$work/projects" ] || exit {_NO_PROJECTS}
"""

# In the restore job, from the work directory: one solution of the listed projects, restored.
RESTORE_SCRIPT = f"""
dotnet new sln -n scan -o . --format sln >/dev/null || exit {_SLN_FAILED}
tr '\\n' '\\0' < projects | xargs -0 dotnet sln scan.sln add >/dev/null || exit {_SLN_FAILED}
exec dotnet restore scan.sln --configfile {DOTNET_CONFIG_DIR}/nuget.config \\
  -p:EnableWindowsTargeting=true -nologo -v:q -tl:off -clp:NoSummary
"""

# In the sandbox: the build's logs as one tar, `$2`, for `take_file`.
_COLLECT_SCRIPT = """
work=$1; out=$2
tar -C "$work/out" -cf "$out" . || exit 1
"""

# An MSBuild error line: `<file>[(line,col)]: error [<CODE>]: <text> [<project>]`. NuGet's own
# errors (an unreadable config) have no code.
_ERROR_LINE = re.compile(
    r"^\s*(?P<file>[^\n]*?)(?:\(\d+(?:,\d+)*\))?\s*:\s*error(?:\s+(?P<code>[A-Z]+[0-9]+))?\s*:"
    r"(?P<text>.*?)(?:\[(?P<project>[^\]\n]+)\])?\s*$",
    re.MULTILINE,
)
_WORKLOADS = re.compile(r"workloads must be installed:\s*([A-Za-z0-9.\-, ]+)")


@dataclass(frozen=True)
class DotnetLimits:
    """How long each step may take: copying the repo, restoring, building."""

    prep_timeout_s: float = 120.0
    restore_timeout_s: float = 300.0
    build_timeout_s: float = 600.0


def error_reason(code: str, text: str = "") -> str:
    """A short, fixed reason for an MSBuild error `code` (the workload names are the only words
    taken from `text`, and only as ids)."""
    if code in ("NU1101", "NU1102", "NU1103"):
        return "restore failed: a package is not on nuget.org"
    if code in ("NU1301", "NU1302", "NU1801"):
        return "restore failed: a package source is not reachable"
    if code == "NETSDK1147":
        found = _WORKLOADS.search(text)
        names = re.findall(r"[a-z0-9][a-z0-9.\-]*", found.group(1).lower()) if found else []
        return f"needs the {' and '.join(names[:3])} workload" if names else "needs a workload"
    if code == "NETSDK1045":
        return "needs a newer .NET SDK"
    if code.startswith("NU"):
        return f"restore failed: {code}"
    return f"build failed: {code}"


def msbuild_errors(output: str, step: str) -> list[tuple[str | None, str]]:
    """Each error line's project (an absolute path in the job, if it names one) and reason;
    `step` (`restore`, `build`) names an error with no code. Compiler errors (`CS…`) are left
    out: they come from the build's logs."""
    errors: list[tuple[str | None, str]] = []
    for match in _ERROR_LINE.finditer(output):
        code = match.group("code") or ""
        if code.startswith("CS"):
            continue
        file = match.group("file").strip()
        # NuGet names the failing project as the file and the solution in brackets; MSBuild
        # names a source or targets file, and the project in brackets.
        project = file if file.endswith("proj") else match.group("project")
        reason = error_reason(code, match.group("text")) if code else f"{step} failed"
        errors.append((project, reason))
    return errors


def _under(path: str, directory: str) -> bool:
    return directory == "." or path == directory or path.startswith(f"{directory}/")


def _owner(path: str, targets: Sequence[LintTarget]) -> LintTarget | None:
    """The target whose module holds `path` (a repo path), the deepest one if modules nest."""
    owners = [t for t in targets if _under(path, t.module)]
    return max(owners, key=lambda t: len(t.module), default=None)


@dataclass
class _Module:
    target: LintTarget
    reason: str | None = None
    logs: int = 0
    compile_errors: int = 0


class _Build:
    """One `scan.lint` .NET build over `targets` in `sandbox`."""

    def __init__(self, sandbox: Sandbox, targets: Sequence[LintTarget], limits: DotnetLimits):
        self._sandbox = sandbox
        self._targets = targets
        self._limits = limits
        self._work = posixpath.join(sandbox.staging_dir, f"dotnet-{uuid4().hex}")
        self._root = f"{self._work}/repo"
        self._modules = {t.module: _Module(t) for t in targets}
        self._findings: dict[tuple[str, str, int | None, str], Finding] = {}

    @property
    def _env(self) -> Mapping[str, str]:
        home = f"{self._work}/home"
        return {
            "HOME": home,
            "DOTNET_CLI_HOME": home,
            "NUGET_PACKAGES": f"{self._work}/nuget",
        }

    def _fail(self, reason: str, modules: Sequence[_Module] | None = None) -> None:
        """Give `reason` to `modules` (default: all) that have none yet."""
        for module in self._modules.values() if modules is None else modules:
            module.reason = module.reason or reason

    def _fail_errors(self, errors: Sequence[tuple[str | None, str]]) -> None:
        """Give each error's reason to the module of its project, or to all if it names none."""
        for project, reason in errors:
            path = project and self._repo_path(project)
            owner = _owner(posixpath.dirname(path), self._targets) if path else None
            self._fail(reason, [self._modules[owner.module]] if owner else None)

    def _repo_path(self, path: str) -> str | None:
        prefix = f"{self._root}/"
        return path[len(prefix) :] if path.startswith(prefix) else None

    async def run(self) -> None:
        try:
            await self._run()
        finally:
            with suppress(SandboxError, ValueError):
                await self._sandbox.exec(["rm", "-rf", "--", self._work])

    async def _run(self) -> None:
        prep = await self._sandbox.exec(
            ["sh", "-c", PREP_SCRIPT, "prep", self._work, *(t.module for t in self._targets)],
            timeout_s=self._limits.prep_timeout_s,
        )
        if prep.exit_code == _NO_PROJECTS:
            return self._fail("no C# project found")
        if prep.exit_code != 0:
            return self._fail("could not copy the repo for the build")

        restore = await self._sandbox.run_job(
            ["sh", "-c", RESTORE_SCRIPT, "restore"],
            network="nuget",
            cwd=self._work,
            timeout_s=self._limits.restore_timeout_s,
            env=self._env,
        )
        if restore.exit_code == TIMED_OUT:
            return self._fail("restore timed out")
        if restore.exit_code == _SLN_FAILED:
            return self._fail("could not load the projects")
        errors = msbuild_errors(restore.stdout, "restore")
        if restore.exit_code != 0 and not errors:
            return self._fail("restore failed")
        # The projects that restored are still built; those that did not keep their reason.
        self._fail_errors(errors)

        build = await self._sandbox.run_job(
            [
                "dotnet", "build", "scan.sln", "--no-restore", "-nologo", "-v:q", "-tl:off",
                "-clp:NoSummary", "--disable-build-servers", "-nodeReuse:false",
                f"-p:CustomAfterMicrosoftCommonTargets={DOTNET_CONFIG_DIR}/scan.targets",
                f"-p:AgenticScanOut={self._work}/out",
            ],
            network="none",
            cwd=self._work,
            timeout_s=self._limits.build_timeout_s,
            env=self._env,
        )  # fmt: skip
        if build.exit_code == TIMED_OUT:
            return self._fail("build timed out")
        await self._read_logs()
        for module in self._modules.values():
            if module.compile_errors:
                count = module.compile_errors
                self._fail(f"does not compile ({count} error{'s' * (count != 1)})", [module])
        self._fail_errors(msbuild_errors(build.stdout, "build"))
        self._fail(
            "the build wrote no analyzer log", [m for m in self._modules.values() if not m.logs]
        )

    async def _read_logs(self) -> None:
        archive = posixpath.join(self._sandbox.staging_dir, f"dotnet-{uuid4().hex}.tar")
        collect = await self._sandbox.exec(
            ["sh", "-c", _COLLECT_SCRIPT, "collect", self._work, archive]
        )
        if collect.exit_code != 0:
            return
        data = await self._sandbox.take_file(archive)
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar:
                extracted = tar.extractfile(member) if member.isfile() else None
                if extracted is not None:
                    files[posixpath.basename(member.name)] = extracted.read()
        for name, content in sorted(files.items()):
            stem, extension = posixpath.splitext(name)
            if extension != ".sarif":
                continue
            project = files.get(f"{stem}.project", b"").decode("utf-8", "replace").strip()
            path = self._repo_path(project)
            owner = _owner(posixpath.dirname(path), self._targets) if path else None
            if owner is None:
                continue
            module = self._modules[owner.module]
            module.logs += 1
            try:
                read = sarif_findings(
                    content.decode("utf-8", "replace"), root=self._root, config=owner.config
                )
            except ScanOutputError:
                self._fail("the build wrote an unreadable analyzer log", [module])
                continue
            module.compile_errors += len(read.compile_errors)
            for finding in read.findings:
                # A file shared by several projects, or built for several target frameworks, is
                # reported once.
                key = (finding.rule, finding.path, finding.line, finding.message)
                self._findings.setdefault(key, finding)

    def result(self, version: str | None) -> tuple[list[Check], list[Finding]]:
        checks: list[Check] = []
        findings: list[Finding] = []
        for module in self._modules.values():
            target = module.target
            mine = [
                f
                for f in self._findings.values()
                if _under(f.path, target.target) and _owner(f.path, self._targets) is target
            ]
            check = Check(
                path=target.target,
                kind=target.kind,
                tool="dotnet",
                config=target.config,
                status="ran",
                version=version,
            )
            if module.reason:
                checks.append(
                    check.model_copy(update={"status": "failed", "reason": module.reason})
                )
                continue
            checks.append(check.model_copy(update={"findings": len(mine)}))
            findings.extend(mine)
        return checks, findings


async def lint_dotnet(
    sandbox: Sandbox,
    targets: Sequence[LintTarget],
    *,
    version: str | None,
    limits: DotnetLimits | None = None,
) -> tuple[list[Check], list[Finding]]:
    """One check per C# module in `targets`, and their findings (fingerprinted without the
    line's text: the caller adds it, as for the other linters)."""
    if not targets:
        return [], []
    if "nuget" not in sandbox.job_networks:
        return [
            Check(
                path=t.target,
                kind=t.kind,
                tool="dotnet",
                config=t.config,
                status="skipped",
                reason=RESTORE_NOT_CONFIGURED,
                version=version,
            )
            for t in targets
        ], []
    build = _Build(sandbox, targets, limits or DotnetLimits())
    await build.run()
    return build.result(version)
