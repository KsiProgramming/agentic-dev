"""The evidence pack at a gate (13.3): what the platform found out about a writer's work before a
person looks at it.

The engine runs `build.test` and `scan.lint` itself (`collect`, through the run's tool executor,
never an agent) and folds their reports into one `EvidencePack`: a `build`, a `tests` and an
`analyzers` check, each `passed`, `failed`, `skipped` or `error`. `analyzers: no_new` compares the
finding fingerprints of the branch with those of the run's base, so old lint debt does not fail a
change that adds none.

A required check that *failed* sends the work back (`send_back_comments`); one that could not run
(`error`: a restore that failed, a timeout) is not the writer's fault, so it reaches the gate for a
person. Test names and messages are repo output: they are capped, and reach the writer as data
under fixed headings.
"""

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agentic_engine.gate import MAX_CHANGE_COMMENTS, GateComment
from agentic_engine.spec import GateEvidence
from agentic_runtime import ToolExecutor

type CheckKind = Literal["build", "tests", "analyzers", "coverage", "criteria"]
type CriterionState = Literal["proven", "untested", "failing", "not_proven", "unchecked"]
type CheckStatus = Literal["passed", "failed", "skipped", "error"]

MAX_LISTED = 20
"""The most failures or findings one check lists in its detail."""
MAX_TEXT = 500
"""The longest message kept of a failure or finding."""

TITLES: dict[CheckKind, str] = {
    "build": "Build",
    "tests": "Tests",
    "analyzers": "Analyzers",
    "coverage": "Coverage",
    "criteria": "Criteria",
}
"""The heading each check has in the comments sent back to the writer."""


class EvidenceCheck(BaseModel):
    """One check of the pack."""

    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    status: CheckStatus
    required: bool = Field(description="Whether a failure of it sends the work back.")
    summary: str = Field(description="One line a person reads at the gate.")
    detail: dict[str, JsonValue] = Field(
        default_factory=lambda: dict[str, JsonValue](),
        description="Capped specifics: failing tests, new findings, modules.",
    )


class EvidencePack(BaseModel):
    """The checks of one gate pass, and how many send-backs remain."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    gate: str
    node: str = Field(description="The writer whose branch was checked.")
    path: str
    checks: list[EvidenceCheck]
    rounds_left: int = Field(ge=0, description="How many more times the checks may send it back.")

    @property
    def failing(self) -> list[EvidenceCheck]:
        """The required checks that failed."""
        return [c for c in self.checks if c.required and c.status == "failed"]

    def sends_back(self) -> bool:
        """Whether the work goes back to the writer: a required check failed and a round is left."""
        return bool(self.failing) and self.rounds_left > 0


class _Failure(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    file: str | None = None
    message: str | None = None


class _Case(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    file: str | None = None
    status: CheckStatus = "error"
    ids: list[str] = Field(default_factory=lambda: list[str]())


class _CoveredFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str = ""
    changed: int = 0
    covered: int = 0
    uncovered: list[tuple[int, int]] = Field(default_factory=lambda: list[tuple[int, int]]())


class _Coverage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    changed: int = 0
    covered: int = 0
    files: list[_CoveredFile] = Field(default_factory=lambda: list[_CoveredFile]())
    truncated: bool = False


class _Module(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str = "."
    ecosystem: str = ""
    runner: str | None = None
    status: CheckStatus = "error"
    reason: str | None = None
    build: Literal["ran", "failed"] | None = None
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    failures: list[_Failure] = Field(default_factory=lambda: list[_Failure]())
    test_ms: int | None = None
    cases: list[_Case] = Field(default_factory=lambda: list[_Case]())
    coverage: _Coverage | None = None
    coverage_reason: str | None = None
    cases_reason: str | None = None


class _TestReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    checks: list[_Module] = Field(default_factory=lambda: list[_Module]())


class _Found(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fingerprint: str | None = None
    tool: str = ""
    rule: str = ""
    path: str = ""
    line: int | None = None
    message: str = ""
    severity: str = "info"


class _Findings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    findings: list[_Found] = Field(default_factory=lambda: list[_Found]())
    checks: list[dict[str, JsonValue]] = Field(default_factory=lambda: list[dict[str, JsonValue]]())


NOTHING_TO_CHECK = "no changes to check"
_NO_WORK = ("has no commits", "has not run before this step")
_TOOL_PREFIX = re.compile(r"^Error executing tool \w+: ")


def _nothing(error: str | None) -> bool:
    """Whether a tool refused because the writer has no committed work: nothing to check, which is
    not a failure of the check."""
    return error is not None and any(text in error for text in _NO_WORK)


def _clip(text: str | None, limit: int = MAX_TEXT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _tests_report(data: Mapping[str, Any] | None) -> _TestReport | None:
    try:
        return _TestReport.model_validate(data) if data is not None else None
    except ValidationError:
        return None


def build_check(report: _TestReport | None, mode: str, error: str | None = None) -> EvidenceCheck:
    """The `build` check from the test report's modules."""
    required = mode == "required"
    if report is None and _nothing(error):
        return EvidenceCheck(
            kind="build", status="skipped", required=required, summary=NOTHING_TO_CHECK
        )
    if report is None:
        return EvidenceCheck(
            kind="build", status="error", required=required, summary=error or "could not build"
        )
    ran = [m for m in report.checks if m.status != "skipped" or m.build is not None]
    broken = [m for m in ran if m.build == "failed"]
    errors = [m for m in ran if m.status == "error"]
    modules: list[JsonValue] = [
        {"path": m.path, "ecosystem": m.ecosystem, "build": m.build or "none", "reason": m.reason}
        for m in report.checks[:MAX_LISTED]
    ]
    detail: dict[str, JsonValue] = {"modules": modules}
    if broken:
        paths = ", ".join(m.path for m in broken[:3])
        return EvidenceCheck(
            kind="build",
            status="failed",
            required=required,
            summary=f"does not build ({paths})",
            detail=detail,
        )
    if errors:
        reason = errors[0].reason or "could not run"
        return EvidenceCheck(
            kind="build", status="error", required=required, summary=reason, detail=detail
        )
    if not ran:
        return EvidenceCheck(
            kind="build",
            status="skipped",
            required=required,
            summary="nothing to build",
            detail=detail,
        )
    return EvidenceCheck(
        kind="build",
        status="passed",
        required=required,
        summary=f"{_count(len(ran), 'module')} built",
        detail=detail,
    )


def tests_check(report: _TestReport | None, mode: str, error: str | None = None) -> EvidenceCheck:
    """The `tests` check from the test report's modules."""
    required = mode == "required"
    if report is None and _nothing(error):
        return EvidenceCheck(
            kind="tests", status="skipped", required=required, summary=NOTHING_TO_CHECK
        )
    if report is None:
        return EvidenceCheck(
            kind="tests", status="error", required=required, summary=error or "could not test"
        )
    ran = [m for m in report.checks if m.runner is not None and m.build != "failed"]
    failing = [m for m in ran if m.status == "failed"]
    errors = [m for m in ran if m.status == "error"]
    passed = sum(m.passed or 0 for m in ran)
    failed = sum(m.failed or 0 for m in ran)
    skipped = sum(m.skipped or 0 for m in ran)
    listed = [f for m in failing for f in m.failures][:MAX_LISTED]
    failures: list[JsonValue] = [
        {"name": _clip(f.name, 200), "file": f.file, "message": _clip(f.message)} for f in listed
    ]
    detail: dict[str, JsonValue] = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "failures": failures,
        "test_ms": sum(m.test_ms or 0 for m in ran),
    }
    if failing:
        counted = passed + failed + skipped
        what = f" ({failed} of {counted})" if counted and failed else ""
        return EvidenceCheck(
            kind="tests",
            status="failed",
            required=required,
            summary=f"tests failed{what}",
            detail=detail,
        )
    if errors:
        return EvidenceCheck(
            kind="tests",
            status="error",
            required=required,
            summary=errors[0].reason or "could not run",
            detail=detail,
        )
    if not ran:
        reasons = [m.reason for m in report.checks if m.reason]
        return EvidenceCheck(
            kind="tests",
            status="skipped",
            required=required,
            summary=reasons[0] if reasons else "no tests found",
            detail=detail,
        )
    return EvidenceCheck(
        kind="tests",
        status="passed",
        required=required,
        summary=f"{_count(passed, 'test')} passed",
        detail=detail,
    )


_SECTION = re.compile(r"^##[ \t]+acceptance criteria[ \t]*$", re.IGNORECASE | re.MULTILINE)
_NEXT_SECTION = re.compile(r"^##[ \t]", re.MULTILINE)
_CRITERION = re.compile(r"(?<![A-Za-z0-9])AC-(\d{3,})(?!\d)")
MAX_CRITERIA = 50
"""The most criteria one spec's check looks at."""

NO_CRITERIA = "no acceptance criteria listed"
NO_CHANGED_LINES = "no changed lines to cover"
_STATE_TEXT: dict[CriterionState, str] = {
    "proven": "a test fails on the base and passes on the change",
    "untested": "no test names it",
    "failing": "a test of it fails on the change",
    "not_proven": "every test of it also passes on the base",
    "unchecked": "its tests could not be checked",
}


def criteria_ids(markdown: str) -> list[str]:
    """The criterion ids (`AC-001`) the `## Acceptance criteria` section of `markdown` lists, in
    order and once each, at most `MAX_CRITERIA`. Everything outside that section is ignored."""
    start = _SECTION.search(markdown)
    if start is None:
        return []
    body = markdown[start.end() :]
    end = _NEXT_SECTION.search(body)
    section = body[: end.start()] if end else body
    return list(dict.fromkeys(f"AC-{d}" for d in _CRITERION.findall(section)))[:MAX_CRITERIA]


def _ranges_text(ranges: Sequence[tuple[int, int]]) -> str:
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def coverage_check(
    report: _TestReport | None, mode: str, minimum: int, error: str | None = None
) -> EvidenceCheck:
    """The `coverage` check: the share of the change's executable lines the tests ran, against
    `minimum` percent. With no changed executable lines it passes; a module that cannot measure it
    (Node, or a run that failed) leaves it an `error`, which reaches a person."""
    required = mode == "required"
    if report is None and _nothing(error):
        return EvidenceCheck(
            kind="coverage", status="skipped", required=required, summary=NOTHING_TO_CHECK
        )
    if report is None:
        return EvidenceCheck(
            kind="coverage",
            status="error",
            required=required,
            summary=error or "coverage could not be measured",
        )
    measured = [m.coverage for m in report.checks if m.coverage is not None]
    reasons = [m.coverage_reason for m in report.checks if m.coverage_reason]
    if not measured:
        if reasons:
            return EvidenceCheck(
                kind="coverage", status="error", required=required, summary=reasons[0]
            )
        return EvidenceCheck(
            kind="coverage", status="skipped", required=required, summary="nothing to measure"
        )
    changed = sum(c.changed for c in measured)
    covered = sum(c.covered for c in measured)
    files = [f for c in measured for f in c.files]
    shown: list[JsonValue] = [
        {
            "path": f.path,
            "changed": f.changed,
            "covered": f.covered,
            "uncovered": [[a, b] for a, b in f.uncovered],
        }
        for f in files[:MAX_LISTED]
    ]
    percent = round(covered * 100 / changed, 1) if changed else 100.0
    detail: dict[str, JsonValue] = {
        "changed": changed,
        "covered": covered,
        "percent": percent,
        "threshold": minimum,
        "files": shown,
        "truncated": any(c.truncated for c in measured) or len(files) > MAX_LISTED,
        "unmeasured": list[JsonValue](reasons[:3]),
    }
    if not changed:
        return EvidenceCheck(
            kind="coverage",
            status="passed",
            required=required,
            summary=NO_CHANGED_LINES,
            detail=detail,
        )
    summary = f"{percent:g}% of changed lines covered ({covered} of {changed}, needs {minimum}%)"
    return EvidenceCheck(
        kind="coverage",
        status="passed" if percent >= minimum else "failed",
        required=required,
        summary=summary,
        detail=detail,
    )


def _cases(report: _TestReport | None) -> list[_Case]:
    return [c for m in report.checks for c in m.cases] if report is not None else []


def criteria_check(
    ids: Sequence[str] | None,
    change: _TestReport | None,
    base: _TestReport | None,
    mode: str,
    *,
    error: str | None = None,
    base_error: str | None = None,
) -> EvidenceCheck:
    """The `criteria` check: for each criterion id, a test (its name holds the id) that fails on
    the base and passes on the change is `proven`. `untested` has no test, `failing` has one that
    fails on the change, `not_proven` has tests that also pass on the base, and `unchecked` could
    not be told (a module that reports no per-test results, or a run that errored). A test the
    base run does not report as passed counts as failing there, which includes one that could not
    be built or collected on the base."""
    required = mode == "required"

    def check(
        status: CheckStatus, summary: str, detail: dict[str, JsonValue] | None = None
    ) -> EvidenceCheck:
        return EvidenceCheck(
            kind="criteria",
            status=status,
            required=required,
            summary=summary,
            detail=detail or {},
        )

    if ids is None:
        return check("error", error or "could not read the criteria")
    if not ids:
        return check("skipped", NO_CRITERIA)
    if change is None and _nothing(error):
        return check("skipped", NOTHING_TO_CHECK)
    if change is None:
        return check("error", error or "could not run the tests")
    blind = any(m.cases_reason or m.status == "error" for m in change.checks if m.runner)
    cases = _cases(change)
    base_cases = {c.name: c for c in _cases(base)}
    base_errored = base is not None and any(m.status == "error" for m in base.checks)
    base_ran = base is not None and not base_errored
    states: list[dict[str, JsonValue]] = []
    counts: dict[CriterionState, int] = dict.fromkeys(_STATE_TEXT, 0)
    for id in ids:
        linked = [c for c in cases if id in c.ids]
        passing = [c for c in linked if c.status == "passed"]
        state: CriterionState
        if any(c.status == "failed" for c in linked):
            state = "failing"
        elif not passing:
            state = "unchecked" if blind else "untested"
        elif not base_ran:
            state = "unchecked"
        elif any(
            base_cases.get(c.name) is None or base_cases[c.name].status != "passed" for c in passing
        ):
            state = "proven"
        else:
            state = "not_proven"
        counts[state] += 1
        tests: list[JsonValue] = [{"name": _clip(c.name, 200), "file": c.file} for c in linked[:5]]
        before: str | None = None
        if state in ("proven", "not_proven"):
            before = "fails" if state == "proven" else "passes"
        states.append(
            {
                "id": id,
                "state": state,
                "tests": tests,
                "before": before,
                "after": "fails" if state == "failing" else "passes" if passing else None,
            }
        )
    gaps = counts["untested"] + counts["failing"] + counts["not_proven"]
    proven = counts["proven"]
    detail: dict[str, JsonValue] = {
        "total": len(ids),
        "proven": proven,
        "criteria": list[JsonValue](states),
        "base_reason": _clip(base_error, 200) if base_error else None,
        "counts": {k: v for k, v in counts.items()},
    }
    summary = f"{proven} of {len(ids)} proven"
    if gaps:
        return check("failed", summary, detail)
    if counts["unchecked"]:
        return check("error", f"{summary}, {counts['unchecked']} could not be checked", detail)
    return check("passed", summary, detail)


def _parse_findings(data: Mapping[str, Any] | None) -> _Findings | None:
    try:
        return _Findings.model_validate(data) if data is not None else None
    except ValidationError:
        return None


def analyzers_check(
    branch: _Findings | None, base: _Findings | None, mode: str, error: str | None = None
) -> EvidenceCheck:
    """The `analyzers` check: what the branch's lint finds that the base's does not (`no_new`),
    or every finding (`shown`)."""
    required = mode == "no_new"
    if branch is None and _nothing(error):
        return EvidenceCheck(
            kind="analyzers", status="skipped", required=required, summary=NOTHING_TO_CHECK
        )
    if branch is None:
        return EvidenceCheck(
            kind="analyzers",
            status="error",
            required=required,
            summary=error or "could not run the analyzers",
        )
    known = {f.fingerprint for f in (base.findings if base else []) if f.fingerprint}
    new = [f for f in branch.findings if not f.fingerprint or f.fingerprint not in known]
    listed: list[JsonValue] = [
        {
            "tool": f.tool,
            "rule": f.rule,
            "path": f.path,
            "line": f.line,
            "severity": f.severity,
            "message": _clip(f.message),
        }
        for f in new[:MAX_LISTED]
    ]
    detail: dict[str, JsonValue] = {
        "new": len(new),
        "total": len(branch.findings),
        "findings": listed,
        "compared_with_base": base is not None,
    }
    if new:
        return EvidenceCheck(
            kind="analyzers",
            status="failed",
            required=required,
            summary=f"{_count(len(new), 'new finding')}",
            detail=detail,
        )
    return EvidenceCheck(
        kind="analyzers",
        status="passed",
        required=required,
        summary="no new findings" if branch.findings else "no findings",
        detail=detail,
    )


def make_pack(
    gate: str,
    evidence: GateEvidence,
    *,
    tests: Mapping[str, Any] | None,
    tests_error: str | None,
    branch: Mapping[str, Any] | None,
    base: Mapping[str, Any] | None,
    lint_error: str | None,
    rounds_left: int,
    base_tests: Mapping[str, Any] | None = None,
    base_tests_error: str | None = None,
    criteria: Sequence[str] | None = None,
    criteria_error: str | None = None,
) -> EvidencePack:
    """The pack from the tools' structured reports (`None` where a call failed, with its error)."""
    checks: list[EvidenceCheck] = []
    report = _tests_report(tests)
    if evidence.checks.build != "off":
        checks.append(build_check(report, evidence.checks.build, tests_error))
    if evidence.checks.tests != "off":
        checks.append(tests_check(report, evidence.checks.tests, tests_error))
    if evidence.checks.analyzers != "off":
        checks.append(
            analyzers_check(
                _parse_findings(branch),
                _parse_findings(base),
                evidence.checks.analyzers,
                lint_error,
            )
        )
    if evidence.checks.coverage != "off":
        checks.append(
            coverage_check(report, evidence.checks.coverage, evidence.coverage_min, tests_error)
        )
    if evidence.checks.criteria != "off":
        checks.append(
            criteria_check(
                criteria,
                report,
                _tests_report(base_tests),
                evidence.checks.criteria,
                error=criteria_error or tests_error,
                base_error=base_tests_error,
            )
        )
    return EvidencePack(
        gate=gate,
        node=evidence.node,
        path=evidence.path,
        checks=checks,
        rounds_left=rounds_left,
    )


def send_back_comments(pack: EvidencePack) -> list[GateComment]:
    """The failures of the pack's required checks as the comments of a request for changes: one
    per failing check's item (`Tests`, `Build`, `Analyzers`), a bullet per failure, so
    `changes_text` hands the writer one section each."""
    comments: list[GateComment] = []
    for check in pack.failing:
        lines: list[str] = [check.summary]
        if check.kind == "tests":
            for f in _items(check.detail.get("failures")):
                where = f" ({f['file']})" if f.get("file") else ""
                message = f": {f['message']}" if f.get("message") else ""
                lines.append(f"{f.get('name', 'a test')}{where}{message}")
        elif check.kind == "coverage":
            for f in _items(check.detail.get("files")):
                missed = [
                    (r[0], r[1])
                    for r in _lists(f.get("uncovered"))
                    if len(r) == 2 and isinstance(r[0], int) and isinstance(r[1], int)
                ]
                if missed:
                    lines.append(f"{f.get('path', '')}: no test runs lines {_ranges_text(missed)}")
        elif check.kind == "criteria":
            for c in _items(check.detail.get("criteria")):
                state = str(c.get("state"))
                if state not in ("untested", "failing", "not_proven"):
                    continue
                names = ", ".join(
                    str(t.get("name", "")) for t in _items(c.get("tests"))[:3] if t.get("name")
                )
                why = _STATE_TEXT[cast("CriterionState", state)]
                lines.append(f"{c.get('id', '')}: {why}" + (f" ({names})" if names else ""))
        elif check.kind == "analyzers":
            for f in _items(check.detail.get("findings")):
                line = f":{f['line']}" if f.get("line") else ""
                lines.append(
                    f"{f.get('path', '')}{line} {f.get('rule', '')}: {f.get('message', '')}"
                )
        else:
            for m in _items(check.detail.get("modules")):
                if m.get("build") == "failed":
                    lines.append(f"{m.get('path', '.')} does not build")
        comments.append(GateComment(item=TITLES[check.kind], text=_bullets(lines)))
    return comments[:MAX_CHANGE_COMMENTS]


def _bullets(lines: Sequence[str]) -> str:
    """The first line as it is and the rest as `- ` bullets, within a comment's cap."""
    head, *rest = lines
    text = head + "".join(f"\n- {_clip(line)}" for line in rest)
    return text if len(text) <= 4000 else text[:3999] + "…"


def _lists(value: JsonValue | None) -> list[list[JsonValue]]:
    return [v for v in value if isinstance(v, list)] if isinstance(value, list) else []


def _items(value: JsonValue | None) -> list[dict[str, JsonValue]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def pack_payload(pack: EvidencePack) -> dict[str, JsonValue]:
    """The pack as JSON, for the event, the artifact and the gate's request."""
    return pack.model_dump(mode="json")


async def collect(
    gate: str,
    evidence: GateEvidence,
    tools: ToolExecutor | None,
    *,
    base_cache: dict[str, Mapping[str, Any] | None],
    rounds_left: int,
    node_id: str,
    read_artifact: Callable[[str], Awaitable[str | None]] | None = None,
) -> EvidencePack:
    """Run the checks of `evidence` on the writer's branch through `tools` and fold them into a
    pack. The base's lint report is read once per run (`base_cache`, by the gate id), and only
    when `analyzers: no_new`. A call that fails leaves its checks `error`."""
    checks = evidence.checks
    tests: Mapping[str, Any] | None = None
    tests_error: str | None = None
    criteria: list[str] | None = None
    criteria_error: str | None = None
    if checks.criteria != "off":
        text = await read_artifact(evidence.criteria_from) if read_artifact is not None else None
        if text is None:
            criteria_error = f"{evidence.criteria_from} was not written"
        else:
            criteria = criteria_ids(text)
    arguments: dict[str, JsonValue] = {"path": evidence.path, "node": evidence.node}
    if checks.coverage != "off":
        arguments["coverage"] = True
    if criteria:
        arguments["select"] = list[JsonValue](criteria)
    base_tests: Mapping[str, Any] | None = None
    base_tests_error: str | None = None
    if (
        checks.build != "off"
        or checks.tests != "off"
        or checks.coverage != "off"
        or checks.criteria != "off"
    ):
        tests, tests_error = await _call(tools, "build.test", arguments, node_id)
    if criteria and tests is not None:
        linked = sorted({i for c in _cases(_tests_report(tests)) for i in c.ids} & set(criteria))
        if linked:
            base_tests, base_tests_error = await _call(
                tools,
                "build.test",
                {
                    "path": evidence.path,
                    "node": evidence.node,
                    "on": "base",
                    "select": list[JsonValue](linked),
                },
                node_id,
            )
    branch: Mapping[str, Any] | None = None
    base: Mapping[str, Any] | None = None
    lint_error: str | None = None
    if checks.analyzers != "off":
        branch, lint_error = await _call(
            tools,
            "scan.lint",
            {"path": evidence.path, "node": evidence.node},
            node_id,
        )
        if checks.analyzers == "no_new" and branch is not None:
            if gate not in base_cache:
                base_cache[gate], _ = await _call(
                    tools, "scan.lint", {"path": evidence.path}, node_id
                )
            base = base_cache[gate]
    return make_pack(
        gate,
        evidence,
        tests=tests,
        tests_error=tests_error,
        branch=branch,
        base=base,
        lint_error=lint_error,
        rounds_left=rounds_left,
        base_tests=base_tests,
        base_tests_error=base_tests_error,
        criteria=criteria,
        criteria_error=criteria_error,
    )


async def _call(
    tools: ToolExecutor | None, name: str, args: dict[str, JsonValue], node_id: str
) -> tuple[Mapping[str, Any] | None, str | None]:
    """One tool call: its structured result, or `None` and a short reason."""
    if tools is None:
        return None, "the run has no tools"
    try:
        output = await tools.call(name, args, node_id=node_id)
    except Exception:
        return None, f"{name} failed"
    if output.is_error or output.data is None:
        if output.is_error:
            return None, _clip(_TOOL_PREFIX.sub("", output.text), 200)
        return None, f"{name} gave no report"
    return output.data, None
