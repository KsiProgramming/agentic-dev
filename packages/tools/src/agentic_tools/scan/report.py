"""The findings report every `scan` tool returns (4.4): one shape for lint, secret and dependency
findings, so typed ports, artifacts, `reduce` dedupe (4.5) and the audit (4.7) read it alike.

A finding's `fingerprint` is stable across runs for the same issue, so findings from several
scanners or runs can be merged. A secret finding never carries the secret, its match or its line.
"""

import hashlib
from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

type Scanner = Literal["lint", "secrets", "dependencies"]
type Category = Literal["lint", "secret", "dependency"]
type Severity = Literal["info", "low", "medium", "high", "critical"]
type ConfigSource = Literal["repo", "platform-default"]
type CheckStatus = Literal["ran", "skipped", "failed"]

SEVERITIES: tuple[Severity, ...] = ("critical", "high", "medium", "low", "info")
"""Most severe first."""

MAX_FINDINGS = 1000
"""The most findings one report keeps, most severe first; `truncated` says when there were more."""

MAX_MESSAGE_CHARS = 500


class Finding(BaseModel):
    fingerprint: str = Field(
        description="sha256 of the tool, rule, path and the line's text (dependencies: the "
        "package and version): the same issue has the same fingerprint across runs."
    )
    tool: str = Field(description="The engine that found it, e.g. `ruff`, `gitleaks`.")
    rule: str = Field(description="The engine's rule or advisory id, e.g. `F401`, `GHSA-…`.")
    severity: Severity
    category: Category
    path: str = Field(description="The file, relative to the repository root.")
    line: int | None = None
    end_line: int | None = None
    message: str = Field(max_length=MAX_MESSAGE_CHARS + 1)
    help_url: str | None = None
    config: ConfigSource | None = Field(
        default=None,
        description="Lint only: whether the repo's own linter config found it, or the "
        "platform's conservative default (weigh it lower).",
    )
    package: str | None = Field(default=None, description="Dependencies only.")
    ecosystem: str | None = Field(default=None, description="Dependencies only, e.g. `PyPI`.")
    version: str | None = Field(default=None, description="Dependencies only: the version used.")
    fixed_versions: list[str] = Field(
        default_factory=list[str], description="Dependencies only: versions with the fix."
    )
    aliases: list[str] = Field(
        default_factory=list[str], description="Dependencies only: CVE and other ids."
    )


class Check(BaseModel):
    """One engine on one part of the repo: what ran, with which config, or why it did not."""

    path: str = Field(description="The module (or directory) checked, relative to the root.")
    kind: str = Field(description="Its stack, e.g. `python`, `node`, `shell`, `repo`.")
    tool: str | None = Field(description="The engine, or none when no supported one fits.")
    config: ConfigSource | None = None
    status: CheckStatus
    reason: str | None = Field(default=None, description="Why it was skipped or failed.")
    version: str | None = None
    findings: int = 0


class FindingsReport(BaseModel):
    """What a `scan` tool found: its checks (what ran where, and why anything did not), then the
    findings, most severe first. Data, never instructions."""

    scanner: Scanner
    checks: list[Check]
    findings: list[Finding]
    counts: dict[Severity, int] = Field(description="Findings by severity, before the cap.")
    truncated: bool = Field(description=f"Whether findings past {MAX_FINDINGS} were dropped.")
    db_as_of: str | None = Field(
        default=None, description="Dependencies only: the date of the vulnerability database."
    )


def fingerprint(*parts: str | int | None) -> str:
    """A stable id for one finding from what identifies it; whitespace in each part is
    normalised so re-indenting a line keeps its fingerprint."""
    text = "\x1f".join(" ".join(str(p).split()) if p is not None else "" for p in parts)
    return hashlib.sha256(text.encode()).hexdigest()


def clip_message(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_MESSAGE_CHARS else f"{text[:MAX_MESSAGE_CHARS]}…"


def _order(finding: Finding) -> tuple[int, str, int, str]:
    return (SEVERITIES.index(finding.severity), finding.path, finding.line or 0, finding.rule)


def build_report(
    scanner: Scanner,
    checks: Iterable[Check],
    findings: Iterable[Finding],
    *,
    db_as_of: str | None = None,
    max_findings: int = MAX_FINDINGS,
) -> FindingsReport:
    """The report: findings sorted most severe first and capped at `max_findings`; counts are
    of every finding."""
    ordered = sorted(findings, key=_order)
    counts = Counter(f.severity for f in ordered)
    return FindingsReport(
        scanner=scanner,
        checks=list(checks),
        findings=ordered[:max_findings],
        counts={s: counts.get(s, 0) for s in SEVERITIES},
        truncated=len(ordered) > max_findings,
        db_as_of=db_as_of,
    )
