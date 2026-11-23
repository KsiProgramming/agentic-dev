"""The test report `build.test` returns (13.3), and how a test job's output is read.

A module's tests run in a job with no network, after the restore and the build (`runner`). Results
are read where the runner writes them (pytest's JUnit file, printed by the job after a marker) or
from the runner's own summary (Jest, Vitest, `node:test`), otherwise from the exit code with no
counts. Everything that reaches the report is capped and a fixed phrase where the tool's words
could quote repo content; test names and messages are repo output, so they stay data.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from agentic_tools.build.stack import Plan, as_table, toml_table

type TestStatus = Literal["passed", "failed", "skipped", "error"]
type TestEcosystem = Literal["node", "python", "dotnet"]

MAX_FAILURES = 20
MAX_CASES = 200
MAX_COVERED_FILES = 20
MAX_RANGES = 20
MAX_TRACKED = 5000
"""The most tests with an id that one run's results keep."""
MAX_MESSAGE = 500
MAX_NAME = 200
JUNIT_MARKER = "::junit::"

NO_NODE_COVERAGE = "coverage is not measured for node yet"
NO_NODE_CASES = "per-test results are not read for node yet"
COVERAGE_FAILED = "coverage could not be measured"
NO_CHANGED_LINES = "no changed lines to cover"
BASE_DID_NOT_BUILD = "the base run did not build"

NO_TESTS = "no tests found"
DOES_NOT_BUILD = "does not build"
TIMED_OUT = "test run timed out"


_ID = re.compile(r"(?<![A-Za-z0-9])AC[-_ ]?(\d{3,})(?!\d)", re.IGNORECASE)
_CRITERION = re.compile(r"AC-\d{3,}")


def criterion_ids(name: str) -> list[str]:
    """The criterion ids a test's name holds, as `AC-001`, in order and once each. An id is its own
    token, with or without its hyphen and in any case (`test_ac_001_x`, `AC001_X`, `t[AC-001]`);
    `TRACK001` is no id, and `AC-0011` is `AC-0011`, never `AC-001`."""
    return list(dict.fromkeys(f"AC-{digits}" for digits in _ID.findall(name)))


def is_criterion_id(text: str) -> bool:
    return _CRITERION.fullmatch(text) is not None


MAX_BUILD_ERRORS = 10
_BUILD_ERROR = re.compile(
    r"^(?P<path>[^\r\n(]+?)\((?P<line>\d+),\d+\):\s*error\s+(?P<code>[A-Za-z]{1,6}\d{1,5})\b:?"
    r"(?P<text>[^\r\n]*?)(?:\s+\[[^\]\r\n]*\])?$",
    re.MULTILINE,
)
_WORK = re.compile(r"/?[^\s'\"]*?(?:dotnet-test|base|tree|build)-[0-9a-f]{32}/(?:repo/)?")
MAX_BUILD_ERROR_TEXT = 200


def build_errors(output: str) -> list[str]:
    """The errors of a failed build as `CODE path:line: message`, once each and at most
    `MAX_BUILD_ERRORS`, so the writer that has to fix them knows what the rule says. The message
    is the tool's and may quote repo content, so it is cut, and the job's work directories are
    taken out of it: it reaches the writer as data under a fixed heading, like a failing test's."""
    found: dict[str, None] = {}
    for match in _BUILD_ERROR.finditer(_ANSI.sub("", output)):
        path = _WORK.sub("", match.group("path").strip())
        text = _clip(_WORK.sub("", match.group("text")).strip(), MAX_BUILD_ERROR_TEXT)
        where = f"{match.group('code')} {path}:{match.group('line')}"
        found[_clip(f"{where}: {text}" if text else where, MAX_BUILD_ERROR_TEXT + MAX_NAME)] = None
    return list(found)[:MAX_BUILD_ERRORS]


def no_runner(language: str) -> str:
    return f"no supported test runner for {language}"


class TestFailure(BaseModel):
    __test__ = False

    name: str = Field(description="The failing test's name.")
    file: str | None = Field(default=None, description="The test file, if the runner said.")
    message: str | None = Field(default=None, description="The failure message, cut.")


class TestCase(BaseModel):
    """One test that names a criterion (13.4): its name holds an id such as `AC-001`."""

    __test__ = False

    name: str = Field(description="The test's name, as the runner reports it.")
    file: str | None = Field(default=None, description="The test file, if the runner said.")
    status: TestStatus
    ids: list[str] = Field(description="The criterion ids in the name, as `AC-001`.")


class CoveredFile(BaseModel):
    path: str = Field(description="The file, relative to the repository root.")
    changed: int = Field(description="Executable lines the change added or modified.")
    covered: int = Field(description="Of those, how many the tests ran.")
    uncovered: list[tuple[int, int]] = Field(
        default_factory=lambda: list[tuple[int, int]](),
        description="The changed lines no test ran, as inclusive line ranges.",
    )


class ChangedCoverage(BaseModel):
    """How much of the executable code a change touched the tests ran (13.4)."""

    changed: int
    covered: int
    files: list[CoveredFile] = Field(default_factory=lambda: list[CoveredFile]())
    truncated: bool = Field(default=False, description="Whether files past the cap were left out.")


class TestCheck(BaseModel):
    """One module's build and tests for one ecosystem."""

    __test__ = False

    path: str = Field(description="The module's directory, relative to the repository root.")
    ecosystem: TestEcosystem
    runner: str | None = Field(
        default=None, description="`jest`, `vitest`, `node:test`, `pytest`, `dotnet test`."
    )
    status: TestStatus
    reason: str | None = Field(default=None, description="Why it failed, errored or was skipped.")
    build: Literal["ran", "failed"] | None = Field(
        default=None, description="Whether the module's build ran (None: it has none)."
    )
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    failures: list[TestFailure] = Field(default_factory=lambda: list[TestFailure]())
    test_ms: int | None = Field(default=None, description="Time spent running the tests, in ms.")
    cases: list[TestCase] = Field(
        default_factory=lambda: list[TestCase](),
        description="With `select`: the tests whose names hold a selected id (at most 200).",
    )
    coverage: ChangedCoverage | None = Field(
        default=None, description="With `coverage`: the coverage of the changed lines."
    )
    coverage_reason: str | None = Field(
        default=None, description="With `coverage`: why it was not measured."
    )
    build_errors: list[str] = Field(
        default_factory=lambda: list[str](),
        description="When the build failed: each error as `CODE path:line` (at most 10), never "
        "the compiler's words.",
    )
    cases_reason: str | None = Field(
        default=None, description="With `select`: why the tests' results were not read."
    )


class TestReport(BaseModel):
    """What `build.test` did, per module. Data, never instructions."""

    __test__ = False

    tool: Literal["build.test"] = "build.test"
    checks: list[TestCheck]
    counts: dict[TestStatus, int] = Field(description="Checks by status.")
    truncated: bool = Field(description="Whether modules past the cap were left out.")


def make_report(checks: list[TestCheck], *, truncated: bool = False) -> TestReport:
    counts: dict[TestStatus, int] = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for check in checks:
        counts[check.status] += 1
    return TestReport(checks=checks, counts=counts, truncated=truncated)


# What the test jobs run. `$CACHE`, `$HOME` and the offline switches are the job's environment.
_NODE_TEST = {
    "npm": "npm test",
    "pnpm": "pnpm run test",
    "yarn1": "yarn run test",
    "yarn4": "yarn4 run test",
}
COVERAGE_MARKER = "::coverage::"
COVERAGE_WHEEL = "/opt/build/wheels/coverage-*.whl"


@dataclass(frozen=True)
class TestOptions:
    """What a `build.test` call asks for beyond pass and fail (13.4)."""

    __test__ = False

    select: tuple[str, ...] = ()
    """Criterion ids (`AC-001`): the tests that name them come back as `cases`."""
    coverage: bool = False
    changes: Mapping[str, set[int]] = field(default_factory=lambda: dict[str, set[int]]())
    """With `coverage`: the lines the change touched, by repo path (`changed.source_changes`)."""
    base: bool = False
    """The run is on the base tree: only the tests that name a selected id run."""


PYTEST_SCRIPT = (
    ".venv/bin/python -m pytest -q -p no:cacheprovider --junitxml=.agentic-junit.xml\n"
    f'code=$?\necho "{JUNIT_MARKER}"\ncat .agentic-junit.xml 2>/dev/null\nexit $code\n'
)


# pytest's `-k` for the ids in `$@` (as `ac_001 or ac001 or ac-001 …`): the test names are matched
# again by `criterion_ids`, so this only narrows what runs. `$@` holds validated ids, never repo
# text.
_PYTEST_SELECT = """
expr=""
for id in "$@"; do
  n=${id#AC-}
  for v in "ac_$n" "ac$n" "ac-$n"; do expr="${expr:+$expr or }$v"; done
done
if [ -n "$expr" ]; then set -- -k "$expr" --continue-on-collection-errors; else set --; fi
"""
_PYTEST = ".venv/bin/python -m pytest -q -p no:cacheprovider --junitxml=.agentic-junit.xml"


def python_script(options: TestOptions | None = None) -> str:
    """The pytest job's script. With `coverage`, coverage.py (the image's pinned wheel) is put in
    the module's venv offline and runs pytest, and its JSON is printed after `::coverage::`; with
    `base`, only the tests that name the ids in `$@` run."""
    options = options or TestOptions()
    if not options.coverage and not options.base:
        return PYTEST_SCRIPT
    head = _PYTEST_SELECT if options.base else "set --\n"
    if options.coverage:
        run = (
            f"uv pip install --config-file /opt/build/uv.toml --python .venv/bin/python --offline "
            f"--no-deps -q {COVERAGE_WHEEL} >/dev/null 2>&1\n"
            f"COVERAGE_FILE=.agentic-cov.dat .venv/bin/python -m coverage run --source=. -m pytest "
            '-q -p no:cacheprovider --junitxml=.agentic-junit.xml "$@"\ncode=$?\n'
            "COVERAGE_FILE=.agentic-cov.dat .venv/bin/python -m coverage json -q "
            "-o .agentic-cov.json >/dev/null 2>&1\n"
            f'echo "{COVERAGE_MARKER}"\ncat .agentic-cov.json 2>/dev/null\n'
        )
    else:
        run = f'{_PYTEST} "$@"\ncode=$?\n'
    return f'{head}{run}echo "{JUNIT_MARKER}"\ncat .agentic-junit.xml 2>/dev/null\nexit $code\n'


def job_script(plan: Plan, options: TestOptions | None = None) -> str:
    """The test job's `sh -c` script for a Node or Python plan."""
    if plan.ecosystem == "node":
        assert plan.manager is not None
        return f"CI=true {_NODE_TEST[plan.manager]}\n"
    return python_script(options)


_PLACEHOLDER = re.compile(r"no test specified", re.IGNORECASE)
_RUNNERS = (("vitest", "vitest"), ("jest", "jest"), ("node --test", "node:test"))


def node_runner(manifest_text: str) -> tuple[str | None, str | None]:
    """The module's `test` script and the runner it names (`jest`, `vitest`, `node:test`, or
    `npm` when it is something else); `(None, None)` when it has no real test script."""
    try:
        data = as_table(json.loads(manifest_text))
    except ValueError:
        return None, None
    script = as_table(data.get("scripts")).get("test")
    if not isinstance(script, str) or not script.strip() or _PLACEHOLDER.search(script):
        return None, None
    for needle, name in _RUNNERS:
        if needle in script:
            return script, name
    return script, "npm"


def python_has_pytest(files: dict[str, str] | object) -> bool:
    """Whether the project depends on pytest or configures it."""
    found = as_table(files)
    for name, text in found.items():
        if name == "pyproject.toml":
            data = toml_table(text)
            tool = as_table(data.get("tool"))
            if "pytest" in tool:
                return True
            if re.search(r"(?i)\bpytest\b", text):
                return True
        elif re.fullmatch(r"requirements.*\.txt", name) and re.search(r"(?im)^\s*pytest\b", text):
            return True
    return False


# --- reading the output ---------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Outcome(BaseModel):
    """What was read from a test job's output."""

    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    failures: list[TestFailure] = Field(default_factory=lambda: list[TestFailure]())
    cases: list[TestCase] = Field(default_factory=lambda: list[TestCase]())

    @property
    def total(self) -> int | None:
        if self.passed is None and self.failed is None:
            return None
        return (self.passed or 0) + (self.failed or 0) + (self.skipped or 0)


def _keep_case(cases: list[TestCase], name: str, file: str | None, status: TestStatus) -> None:
    ids = criterion_ids(name)
    if ids and len(cases) < MAX_TRACKED:
        cases.append(
            TestCase(
                name=_clip(name, MAX_NAME),
                file=_clip(file, MAX_NAME) if file else None,
                status=status,
                ids=ids,
            )
        )


def parse_junit(text: str) -> Outcome | None:
    """Counts and failures from a JUnit XML document, or None when it is not one. A document with
    a DTD or entities is refused: the file is written by repo code."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        root = ET.fromstring(text.strip())
    except ET.ParseError:
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return None
    total = failed = skipped = 0
    failures: list[TestFailure] = []
    cases: list[TestCase] = []
    for case in root.iter("testcase"):
        total += 1
        bad = next((c for c in case if c.tag in ("failure", "error")), None)
        skip = bad is None and any(c.tag == "skipped" for c in case)
        _keep_case(
            cases,
            f"{case.get('classname', '')}::{case.get('name', '')}".strip(":"),
            case.get("file") or (case.get("classname", "").replace(".", "/") + ".py" or None),
            "failed" if bad is not None else "skipped" if skip else "passed",
        )
        if bad is not None:
            failed += 1
            if len(failures) < MAX_FAILURES:
                name = _clip(
                    f"{case.get('classname', '')}::{case.get('name', '')}".strip(":"), MAX_NAME
                )
                file = case.get("file") or (
                    case.get("classname", "").replace(".", "/") + ".py" or None
                )
                message = bad.get("message") or (bad.text or "")
                failures.append(
                    TestFailure(
                        name=name,
                        file=_clip(file, MAX_NAME) if file else None,
                        message=_clip(message, MAX_MESSAGE) or None,
                    )
                )
        elif any(c.tag == "skipped" for c in case):
            skipped += 1
    return Outcome(
        passed=total - failed - skipped,
        failed=failed,
        skipped=skipped,
        failures=failures,
        cases=cases,
    )


TRX_MARKER = "::trx::"


def split_trx(stdout: str) -> tuple[str, list[str]]:
    """A `dotnet test` job's output as (the runner's own output, each TRX document after the
    marker)."""
    head, found, tail = stdout.partition(f"{TRX_MARKER}\n")
    if not found:
        return stdout, []
    # dotnet writes each TRX with a byte-order mark, which would trail the document before it.
    tail = tail.replace("\ufeff", "")
    documents = [f"<?xml{part}" for part in tail.split("<?xml") if part.strip()]
    return head, documents


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_trx(documents: list[str]) -> Outcome | None:
    """Counts and failures from TRX documents (one per test project), or None when none is a TRX
    file. A document with a DTD or entities is skipped: the file is written by repo code."""
    total = failed = skipped = 0
    failures: list[TestFailure] = []
    cases: list[TestCase] = []
    found = False
    for text in documents:
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            continue
        try:
            root = ET.fromstring(text.strip())
        except ET.ParseError:
            continue
        if _local(root.tag) != "TestRun":
            continue
        found = True
        classes: dict[str, str] = {}
        for node in root.iter():
            if _local(node.tag) == "UnitTest":
                method = next((c for c in node.iter() if _local(c.tag) == "TestMethod"), None)
                if method is not None and node.get("id"):
                    classes[node.get("id", "")] = method.get("className", "")
        for result in root.iter():
            if _local(result.tag) != "UnitTestResult":
                continue
            outcome = result.get("outcome", "")
            owner = classes.get(result.get("testId", ""), "")
            status: TestStatus = (
                "skipped"
                if outcome == "NotExecuted"
                else "passed"
                if outcome == "Passed"
                else "failed"
            )
            _keep_case(cases, result.get("testName", ""), owner or None, status)
            if outcome == "NotExecuted":
                skipped += 1
                continue
            total += 1
            if outcome == "Passed":
                continue
            failed += 1
            if len(failures) >= MAX_FAILURES:
                continue
            message = next((m.text or "" for m in result.iter() if _local(m.tag) == "Message"), "")
            failures.append(
                TestFailure(
                    name=_clip(result.get("testName", "a test"), MAX_NAME),
                    file=_clip(owner, MAX_NAME) or None,
                    message=_clip(message, MAX_MESSAGE) or None,
                )
            )
    if not found:
        return None
    return Outcome(
        passed=total - failed, failed=failed, skipped=skipped, failures=failures, cases=cases
    )


def split_coverage(head: str) -> tuple[str, str]:
    """What precedes a test job's JUnit file as (the runner's own output, the coverage report
    printed after `::coverage::`)."""
    output, found, report = head.partition(f"{COVERAGE_MARKER}\n")
    return (output, report) if found else (head, "")


def split_junit(stdout: str) -> tuple[str, str]:
    """A pytest job's output as (the runner's own output, the JUnit file after the marker)."""
    head, _, tail = stdout.rpartition(f"{JUNIT_MARKER}\n")
    return (head, tail) if head or tail else (stdout, "")


_JEST = re.compile(r"^Tests:\s+(?P<body>.*\d+ total)\s*$", re.MULTILINE)
_VITEST = re.compile(r"^\s*Tests\s+(?P<body>.*\(\d+\))\s*$", re.MULTILINE)
_NODE_SPEC = re.compile(r"^ℹ (tests|pass|fail|skipped) (\d+)\s*$", re.MULTILINE)  # noqa: RUF001 (node:test prints it)
_NODE_TAP = re.compile(r"^# (tests|pass|fail|skipped) (\d+)\s*$", re.MULTILINE)
_TOKEN = re.compile(r"(\d+) (failed|passed|skipped|todo)")


def _counts(body: str) -> Outcome:
    found = {k: int(n) for n, k in _TOKEN.findall(body)}
    return Outcome(
        passed=found.get("passed", 0),
        failed=found.get("failed", 0),
        skipped=found.get("skipped", 0),
    )


def parse_node_output(runner: str | None, output: str) -> Outcome | None:
    """Counts and failures from a Node runner's summary, or None when none is recognised."""
    text = _ANSI.sub("", output)
    outcome: Outcome | None = None
    if match := _JEST.search(text):
        outcome = _counts(match.group("body"))
        outcome.failures = _jest_failures(text)
    elif match := _VITEST.search(text):
        outcome = _counts(match.group("body"))
        outcome.failures = _vitest_failures(text)
    else:
        for pattern, failing in (
            (_NODE_SPEC, _node_spec_failures),
            (_NODE_TAP, _node_tap_failures),
        ):
            pairs = dict(pattern.findall(text))
            if "tests" in pairs:
                outcome = Outcome(
                    passed=int(pairs.get("pass", 0)),
                    failed=int(pairs.get("fail", 0)),
                    skipped=int(pairs.get("skipped", 0)),
                    failures=failing(text),
                )
                break
    return outcome


_JEST_FAIL = re.compile(r"^\s*● (?P<name>.+?)\s*$", re.MULTILINE)


def _jest_failures(text: str) -> list[TestFailure]:
    failures: list[TestFailure] = []
    file = None
    for line in text.splitlines():
        if (m := re.match(r"^\s*FAIL\s+(\S+)", line)) is not None:
            file = m.group(1)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _JEST_FAIL.match(line)
        if not match or " › " not in match.group("name") or len(failures) >= MAX_FAILURES:  # noqa: RUF001
            continue
        message = [m.strip() for m in lines[i + 1 : i + 8] if m.strip()][:3]
        failures.append(
            TestFailure(
                name=_clip(match.group("name"), MAX_NAME),
                file=_clip(file, MAX_NAME) if file else None,
                message=_clip(" ".join(message), MAX_MESSAGE) or None,
            )
        )
    return failures


_VITEST_FAIL = re.compile(r"^\s*FAIL\s+(?P<file>\S+)\s*>\s*(?P<name>.+?)\s*$", re.MULTILINE)


def _vitest_failures(text: str) -> list[TestFailure]:
    lines = text.splitlines()
    failures: list[TestFailure] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        match = _VITEST_FAIL.match(line)
        if not match or len(failures) >= MAX_FAILURES:
            continue
        key = f"{match.group('file')}>{match.group('name')}"
        if key in seen:
            continue
        seen.add(key)
        message = [m.strip() for m in lines[i + 1 : i + 6] if m.strip() and not m.startswith("-")]
        failures.append(
            TestFailure(
                name=_clip(match.group("name"), MAX_NAME),
                file=_clip(match.group("file"), MAX_NAME),
                message=_clip(" ".join(message[:2]), MAX_MESSAGE) or None,
            )
        )
    return failures


def _node_spec_failures(text: str) -> list[TestFailure]:
    names = re.findall(r"^\s*✖ (.+?)(?: \([\d.]+ms\))?\s*$", text, re.MULTILINE)
    return [TestFailure(name=_clip(n, MAX_NAME)) for n in dict.fromkeys(names)][:MAX_FAILURES]


def _node_tap_failures(text: str) -> list[TestFailure]:
    names = re.findall(r"^\s*not ok \d+ - (.+?)\s*$", text, re.MULTILINE)
    return [TestFailure(name=_clip(n, MAX_NAME)) for n in dict.fromkeys(names)][:MAX_FAILURES]


def tests_failed_reason(outcome: Outcome | None) -> str:
    """`tests failed (N of M)`, or plain `tests failed` when the runner gave no counts."""
    if outcome is None or outcome.total is None or outcome.failed is None:
        return "tests failed"
    return f"tests failed ({outcome.failed} of {outcome.total})"


__all__ = [
    "COVERAGE_FAILED",
    "DOES_NOT_BUILD",
    "NO_CHANGED_LINES",
    "NO_NODE_CASES",
    "NO_NODE_COVERAGE",
    "NO_TESTS",
    "TIMED_OUT",
    "ChangedCoverage",
    "Outcome",
    "TestCase",
    "TestCheck",
    "TestFailure",
    "TestOptions",
    "TestReport",
    "build_errors",
    "criterion_ids",
    "job_script",
    "make_report",
    "no_runner",
    "node_runner",
    "parse_junit",
    "parse_node_output",
    "parse_trx",
    "python_has_pytest",
    "python_script",
    "split_coverage",
    "split_junit",
    "split_trx",
    "tests_failed_reason",
]
