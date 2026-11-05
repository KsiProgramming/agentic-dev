"""Each scanner's own JSON, read into `Finding`s. Paths come out relative to the repository root;
a finding whose path leaves the repo is dropped. A lint finding's fingerprint is made without its
line's text here; `with_line_texts` makes it again once the server has read the lines.

Each tool's output is read through a small model of the fields we use (others are ignored), so
a tool that changes its format fails loudly as `ScanOutputError`.

Severities map to ours in one table per tool (`SEVERITY_MAPS`, and `cvss_severity` for
advisories). A linter's "error" is `medium`: lint findings are likely bugs, not incidents. A
leaked secret is always `high`. A vulnerability takes its CVSS score's band, `medium` when the
advisory has none.

gitleaks' `Match`, `Secret` and the line's text are not even in its model.
"""

import posixpath
import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from agentic_tools.repo.paths import repo_relative
from agentic_tools.scan.report import ConfigSource, Finding, Severity, clip_message, fingerprint

SEVERITY_MAPS: Mapping[str, Mapping[str, Severity]] = {
    # ruff reports every rule as "error".
    "ruff": {"error": "medium", "warning": "low"},
    # Biome's GitLab reporter: error -> critical, warning -> major, information -> minor.
    "biome": {"blocker": "high", "critical": "medium", "major": "low", "minor": "info"},
    "shellcheck": {"error": "medium", "warning": "low", "info": "info", "style": "info"},
    # SARIF levels of a .NET build (4.8); `none` (a hidden diagnostic) is dropped.
    "dotnet": {"error": "medium", "warning": "low", "note": "info"},
}


class ScanOutputError(ValueError):
    """A scanner's output is not what it should be."""


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


def _parse[T](adapter: TypeAdapter[T], raw: str) -> T:
    try:
        return adapter.validate_json(raw)
    except ValidationError as e:
        error = e.errors()[0]
        where = "/".join(str(p) for p in error["loc"])
        raise ScanOutputError(f"{error['msg']} at /{where}" if where else error["msg"]) from None


def _relative(path: str, base: str) -> str | None:
    """`path` (absolute under `base`, or relative to it) relative to the repo root."""
    path = path.replace("\\", "/")
    base = base.replace("\\", "/").rstrip("/")
    if path.startswith(f"{base}/"):
        path = path[len(base) + 1 :]
    return repo_relative(path)


def _join(directory: str, path: str) -> str | None:
    relative = repo_relative(path)
    if relative is None:
        return None
    return repo_relative(posixpath.join(directory, relative))


def _severity(tool: str, level: str) -> Severity:
    return SEVERITY_MAPS[tool].get(level.lower(), "medium")


# Ruff: `ruff check --output-format json`.


class _RuffLocation(_In):
    row: int | None = None


class _RuffDiagnostic(_In):
    code: str | None = None
    filename: str
    location: _RuffLocation | None = None
    end_location: _RuffLocation | None = None
    message: str = ""
    severity: str = "error"
    url: str | None = None


_RUFF = TypeAdapter(list[_RuffDiagnostic])


def ruff_findings(raw: str, *, workdir: str, config: ConfigSource) -> list[Finding]:
    """ruff's diagnostics, whose file names are absolute in the sandbox."""
    findings: list[Finding] = []
    for item in _parse(_RUFF, raw):
        path = _relative(item.filename, workdir)
        if path is None:
            continue
        rule = item.code or "syntax-error"
        findings.append(
            Finding(
                fingerprint=fingerprint("ruff", rule, path),
                tool="ruff",
                rule=rule,
                severity=_severity("ruff", item.severity),
                category="lint",
                path=path,
                line=item.location.row if item.location else None,
                end_line=item.end_location.row if item.end_location else None,
                message=clip_message(item.message),
                help_url=item.url,
                config=config,
            )
        )
    return findings


# Biome: `biome lint --reporter=gitlab`, run in a module.


class _BiomeLines(_In):
    begin: int | None = None
    end: int | None = None


class _BiomeLocation(_In):
    path: str
    lines: _BiomeLines = Field(default_factory=_BiomeLines)


class _BiomeDiagnostic(_In):
    check_name: str
    description: str = ""
    severity: str = "critical"
    location: _BiomeLocation


_BIOME = TypeAdapter(list[_BiomeDiagnostic])
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _biome_url(rule: str) -> str:
    """`suspicious/noDoubleEquals` -> the rule's page."""
    name = rule.rsplit("/", 1)[-1]
    return f"https://biomejs.dev/linter/rules/{_CAMEL.sub('-', name).lower()}/"


def biome_findings(raw: str, *, module: str, config: ConfigSource) -> list[Finding]:
    """Biome's diagnostics, with paths relative to `module`. Diagnostics that are not lint rules
    (a deprecated config key, a file it cannot parse) are not findings."""
    findings: list[Finding] = []
    for item in _parse(_BIOME, raw):
        if not item.check_name.startswith("lint/"):
            continue
        path = _join(module, item.location.path)
        if path is None:
            continue
        rule = item.check_name.removeprefix("lint/")
        findings.append(
            Finding(
                fingerprint=fingerprint("biome", rule, path),
                tool="biome",
                rule=rule,
                severity=_severity("biome", item.severity),
                category="lint",
                path=path,
                line=item.location.lines.begin,
                end_line=item.location.lines.end,
                message=clip_message(item.description),
                help_url=_biome_url(rule),
                config=config,
            )
        )
    return findings


# ShellCheck: `shellcheck -f json1`, run at the repo root on repo-relative files.


class _ShellCheckComment(_In):
    file: str
    line: int | None = None
    end_line: int | None = Field(default=None, alias="endLine")
    level: str = "warning"
    code: int
    message: str = ""


class _ShellCheckReport(_In):
    comments: list[_ShellCheckComment]


_SHELLCHECK = TypeAdapter(_ShellCheckReport)


def shellcheck_findings(raw: str, *, config: ConfigSource) -> list[Finding]:
    findings: list[Finding] = []
    for item in _parse(_SHELLCHECK, raw).comments:
        path = repo_relative(item.file)
        if path is None:
            continue
        rule = f"SC{item.code}"
        findings.append(
            Finding(
                fingerprint=fingerprint("shellcheck", rule, path),
                tool="shellcheck",
                rule=rule,
                severity=_severity("shellcheck", item.level),
                category="lint",
                path=path,
                line=item.line,
                end_line=item.end_line,
                message=clip_message(item.message),
                help_url=f"https://www.shellcheck.net/wiki/{rule}",
                config=config,
            )
        )
    return findings


# gitleaks: `gitleaks dir --redact --report-format json`. Only these fields are read.


class _Leak(_In):
    rule_id: str = Field(alias="RuleID")
    description: str = Field(default="", alias="Description")
    start_line: int | None = Field(default=None, alias="StartLine")
    end_line: int | None = Field(default=None, alias="EndLine")
    file: str = Field(alias="File")


_GITLEAKS = TypeAdapter(list[_Leak] | None)


def gitleaks_findings(raw: str, *, workdir: str) -> list[Finding]:
    """gitleaks' leaks, with file paths relative to the repo root or absolute in it."""
    findings: list[Finding] = []
    for item in _parse(_GITLEAKS, raw) or []:
        path = _relative(item.file, workdir)
        if path is None:
            continue
        findings.append(
            Finding(
                fingerprint=fingerprint("gitleaks", item.rule_id, path, item.start_line),
                tool="gitleaks",
                rule=item.rule_id,
                severity="high",
                category="secret",
                path=path,
                line=item.start_line,
                end_line=item.end_line,
                message=clip_message(item.description or "A secret in the code"),
            )
        )
    return findings


# .NET (4.8): one SARIF 2.1 log per project and target framework, written by the compiler during
# `scan.lint`'s build (`agentic_tools.scan.dotnet`), with every compiler and analyzer diagnostic.


class _SarifRegion(_In):
    start_line: int | None = Field(default=None, alias="startLine")
    end_line: int | None = Field(default=None, alias="endLine")


class _SarifArtifact(_In):
    uri: str


class _SarifPhysical(_In):
    artifact_location: _SarifArtifact = Field(alias="artifactLocation")
    region: _SarifRegion = Field(default_factory=_SarifRegion)


class _SarifLocation(_In):
    physical_location: _SarifPhysical | None = Field(default=None, alias="physicalLocation")


class _SarifMessage(_In):
    text: str = ""


class _SarifResult(_In):
    rule_id: str = Field(alias="ruleId")
    level: str = "warning"
    message: _SarifMessage = Field(default_factory=_SarifMessage)
    locations: list[_SarifLocation] = Field(default_factory=list[_SarifLocation])
    suppressions: list[object] = Field(default_factory=list[object])


class _SarifRule(_In):
    id: str
    help_uri: str | None = Field(default=None, alias="helpUri")


class _SarifDriver(_In):
    rules: list[_SarifRule] = Field(default_factory=list[_SarifRule])


class _SarifTool(_In):
    driver: _SarifDriver = Field(default_factory=_SarifDriver)


class _SarifRun(_In):
    tool: _SarifTool = Field(default_factory=_SarifTool)
    results: list[_SarifResult] = Field(default_factory=list[_SarifResult])


class _SarifLog(_In):
    runs: list[_SarifRun]


_SARIF = TypeAdapter(_SarifLog)
_GENERATED_DIRS = frozenset({"bin", "obj"})


class SarifRead(NamedTuple):
    """A .NET build's log, read: its findings, and where each compiler error is (a repo path)."""

    findings: list[Finding]
    compile_errors: list[str]


def _sarif_path(uri: str, root: str) -> str | None:
    """The repo path of a SARIF `file://` URI under `root` (the build's copy of the repo), or
    `None` outside it or in build output (`bin/`, `obj/`: generated, not the repo's code)."""
    parsed = urlparse(uri)
    if parsed.scheme not in ("", "file"):
        return None
    path = _relative(unquote(parsed.path), root)
    if path is None or _GENERATED_DIRS.intersection(path.split("/")):
        return None
    return path


def sarif_findings(raw: str, *, root: str, config: ConfigSource) -> SarifRead:
    """The diagnostics of one SARIF log whose file URIs are under `root`. Suppressed ones
    (`#pragma`, `[SuppressMessage]`), hidden ones and ones with no file location are dropped.
    A compiler error (`CS…` at level error) is not a finding: the build did not compile, so its
    path is returned in `compile_errors` for the check to say so."""
    findings: list[Finding] = []
    compile_errors: list[str] = []
    for run in _parse(_SARIF, raw).runs:
        help_urls = {rule.id: rule.help_uri for rule in run.tool.driver.rules}
        for result in run.results:
            level = result.level.lower()
            if result.suppressions or level not in SEVERITY_MAPS["dotnet"]:
                continue
            physical = result.locations[0].physical_location if result.locations else None
            path = _sarif_path(physical.artifact_location.uri, root) if physical else None
            if level == "error" and result.rule_id.startswith("CS"):
                compile_errors.append(path or "")
                continue
            if physical is None or path is None:
                continue
            findings.append(
                Finding(
                    fingerprint=fingerprint("dotnet", result.rule_id, path),
                    tool="dotnet",
                    rule=result.rule_id,
                    severity=_severity("dotnet", level),
                    category="lint",
                    path=path,
                    line=physical.region.start_line,
                    end_line=physical.region.end_line,
                    message=clip_message(result.message.text),
                    help_url=help_urls.get(result.rule_id),
                    config=config,
                )
            )
    return SarifRead(findings, compile_errors)


# osv-scanner: `osv-scanner scan source --format json`.


class _OsvEvent(_In):
    fixed: str | None = None


class _OsvRange(_In):
    events: list[_OsvEvent] = Field(default_factory=list[_OsvEvent])


class _OsvPackageRef(_In):
    name: str = ""


class _OsvAffected(_In):
    package: _OsvPackageRef = Field(default_factory=_OsvPackageRef)
    ranges: list[_OsvRange] = Field(default_factory=list[_OsvRange])


class _OsvVuln(_In):
    id: str
    summary: str | None = None
    details: str | None = None
    affected: list[_OsvAffected] = Field(default_factory=list[_OsvAffected])


class _OsvGroup(_In):
    ids: list[str] = Field(default_factory=list[str])
    aliases: list[str] = Field(default_factory=list[str])
    max_severity: str | None = None


class _OsvPackage(_In):
    name: str
    version: str | None = None
    ecosystem: str | None = None


class _OsvPackageResult(_In):
    package: _OsvPackage
    groups: list[_OsvGroup] = Field(default_factory=list[_OsvGroup])
    vulnerabilities: list[_OsvVuln] = Field(default_factory=list[_OsvVuln])


class _OsvSource(_In):
    path: str


class _OsvResult(_In):
    source: _OsvSource
    packages: list[_OsvPackageResult] = Field(default_factory=list[_OsvPackageResult])


class _OsvReport(_In):
    results: list[_OsvResult] | None = None


_OSV = TypeAdapter(_OsvReport)


def cvss_severity(score: str | None) -> Severity:
    """A CVSS base score's band; `medium` when there is none."""
    try:
        value = float(score or "")
    except ValueError:
        return "medium"
    if value >= 9.0:
        return "critical"
    if value >= 7.0:
        return "high"
    if value >= 4.0:
        return "medium"
    return "low" if value > 0 else "medium"


def _fixed_versions(vulns: Sequence[_OsvVuln], package: str) -> list[str]:
    return sorted(
        {
            event.fixed
            for vuln in vulns
            for affected in vuln.affected
            if affected.package.name == package
            for r in affected.ranges
            for event in r.events
            if event.fixed is not None
        }
    )


def osv_findings(raw: str, *, workdir: str) -> list[Finding]:
    """One finding per advisory group of each package of each lockfile."""
    findings: list[Finding] = []
    for result in _parse(_OSV, raw).results or []:
        path = _relative(result.source.path, workdir)
        if path is None:
            continue
        for entry in result.packages:
            name, version = entry.package.name, entry.package.version
            for group in entry.groups:
                if not group.ids:
                    continue
                rule = next((i for i in group.ids if i.startswith("GHSA-")), group.ids[0])
                vulns = [v for v in entry.vulnerabilities if v.id in group.ids]
                summary = next(
                    (v.summary or v.details for v in vulns if v.summary or v.details),
                    "a known vulnerability",
                )
                findings.append(
                    Finding(
                        fingerprint=fingerprint("osv-scanner", rule, path, name, version),
                        tool="osv-scanner",
                        rule=rule,
                        severity=cvss_severity(group.max_severity),
                        category="dependency",
                        path=path,
                        message=clip_message(f"{name} {version}: {summary}"),
                        help_url=f"https://osv.dev/vulnerability/{rule}",
                        package=name,
                        ecosystem=entry.package.ecosystem,
                        version=version,
                        fixed_versions=_fixed_versions(vulns, name),
                        aliases=sorted(set(group.aliases) - {rule}),
                    )
                )
    return findings


def with_line_texts(
    findings: Sequence[Finding], texts: Mapping[tuple[str, int], str]
) -> list[Finding]:
    """Lint `findings` with fingerprints over their line's text (`(path, line)` -> text), so a
    finding keeps its fingerprint when lines above it move."""
    return [
        f.model_copy(
            update={
                "fingerprint": fingerprint(
                    f.tool, f.rule, f.path, texts.get((f.path, f.line)) if f.line else None
                )
            }
        )
        for f in findings
    ]
