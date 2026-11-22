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
from typing import Literal

from pydantic import BaseModel, Field

from agentic_tools.build.stack import Plan, as_table, toml_table

type TestStatus = Literal["passed", "failed", "skipped", "error"]
type TestEcosystem = Literal["node", "python", "dotnet"]

MAX_FAILURES = 20
MAX_MESSAGE = 500
MAX_NAME = 200
JUNIT_MARKER = "::junit::"

NO_TESTS = "no tests found"
DOES_NOT_BUILD = "does not build"
TIMED_OUT = "test run timed out"


def no_runner(language: str) -> str:
    return f"no supported test runner for {language}"


class TestFailure(BaseModel):
    __test__ = False

    name: str = Field(description="The failing test's name.")
    file: str | None = Field(default=None, description="The test file, if the runner said.")
    message: str | None = Field(default=None, description="The failure message, cut.")


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
PYTEST_SCRIPT = (
    ".venv/bin/python -m pytest -q -p no:cacheprovider --junitxml=.agentic-junit.xml\n"
    f'code=$?\necho "{JUNIT_MARKER}"\ncat .agentic-junit.xml 2>/dev/null\nexit $code\n'
)


def job_script(plan: Plan) -> str:
    """The test job's `sh -c` script for a Node or Python plan."""
    if plan.ecosystem == "node":
        assert plan.manager is not None
        return f"CI=true {_NODE_TEST[plan.manager]}\n"
    return PYTEST_SCRIPT


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

    @property
    def total(self) -> int | None:
        if self.passed is None and self.failed is None:
            return None
        return (self.passed or 0) + (self.failed or 0) + (self.skipped or 0)


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
    for case in root.iter("testcase"):
        total += 1
        bad = next((c for c in case if c.tag in ("failure", "error")), None)
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
        passed=total - failed - skipped, failed=failed, skipped=skipped, failures=failures
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
            owner = classes.get(result.get("testId", ""), "")
            failures.append(
                TestFailure(
                    name=_clip(result.get("testName", "a test"), MAX_NAME),
                    file=_clip(owner, MAX_NAME) or None,
                    message=_clip(message, MAX_MESSAGE) or None,
                )
            )
    if not found:
        return None
    return Outcome(passed=total - failed, failed=failed, skipped=skipped, failures=failures)


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
    "DOES_NOT_BUILD",
    "NO_TESTS",
    "TIMED_OUT",
    "Outcome",
    "TestCheck",
    "TestFailure",
    "TestReport",
    "job_script",
    "make_report",
    "no_runner",
    "node_runner",
    "parse_junit",
    "parse_node_output",
    "parse_trx",
    "python_has_pytest",
    "split_junit",
    "split_trx",
    "tests_failed_reason",
]
