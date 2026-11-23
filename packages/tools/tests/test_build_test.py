# ruff: noqa: RUF001, E501
"""`build.test` on a scripted sandbox (13.3): which tests run for which module, every outcome turned
into a fixed reason, and the output of each runner read into counts and capped failures. The real
jobs run in `test_build_docker.py`."""

import json
from collections.abc import Mapping, Sequence

from agentic_sandbox import ExecResult, JobNetwork
from agentic_tools.build import BuildLimits
from agentic_tools.build.runner import test_modules as run_tests
from agentic_tools.build.tests import (
    JUNIT_MARKER,
    MAX_FAILURES,
    MAX_MESSAGE,
    TestOptions,
    parse_junit,
    parse_node_output,
)

JEST_FAIL = """\
FAIL src/sum.test.js
  ● sum › adds
    expect(received).toBe(expected)
    Expected: 3
    Received: 4

Tests:       1 failed, 2 passed, 3 total
"""
VITEST_FAIL = """\
 FAIL  src/sum.test.ts > sum > adds
AssertionError: expected 4 to be 3

 Test Files  1 failed (1)
      Tests  1 failed | 2 passed (3)
"""
NODE_SPEC = "✖ adds (1.2ms)\nℹ tests 3\nℹ pass 2\nℹ fail 1\nℹ skipped 0\n"
NODE_TAP = "not ok 1 - adds\n# tests 3\n# pass 2\n# fail 1\n# skipped 0\n"
JUNIT = """\
<testsuites><testsuite tests="3">
<testcase classname="tests.test_sum" name="test_ok"/>
<testcase classname="tests.test_sum" name="test_adds"><failure message="assert 4 == 3">tb</failure></testcase>
<testcase classname="tests.test_sum" name="test_later"><skipped/></testcase>
</testsuite></testsuites>"""


STAGING = "/workspace/.incoming"
PYPROJECT = """[project]
name = "demo"
version = "0.1.0"
dependencies = ["pydantic==2.11.7"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


class BuildSandbox:
    """Answers the steps of a restore: the module listing, each module's files, the copy and the
    restore and build jobs (scripted results)."""

    workdir = "/workspace/repo"
    staging_dir = STAGING

    def __init__(
        self,
        modules: Mapping[str, Mapping[str, str]],
        *,
        restore: ExecResult | None = None,
        build: ExecResult | None = None,
    ) -> None:
        self.modules = modules
        self.restore = restore or ExecResult(0, "::packages:: 42\n", "")
        self.build = build or ExecResult(0, "", "")
        self.job_networks: frozenset[JobNetwork] = frozenset({"none", "npm", "pypi"})

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = 30.0, cwd: str | None = None
    ) -> ExecResult:
        if argv[0] == "rm":
            return ExecResult(0, "", "")
        step = argv[3]
        if step == "modules":
            listing = "".join(
                "./package.json\n" if m == "." else f"./{m}/package.json\n" for m in self.modules
            )
            return ExecResult(0, f"{listing}::dirs::\n", "")
        if step == "describe":
            module, marker = argv[4], argv[5]
            out = "".join(f"{marker} {n}\n{t}\n" for n, t in self.modules[module].items())
            return ExecResult(0, out, "")
        assert step == "copy"
        return ExecResult(0, "", "")

    async def put_file(self, data: bytes) -> str:
        return f"{STAGING}/staged"

    async def run_job(
        self,
        argv: Sequence[str],
        *,
        network: JobNetwork,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        return self.restore if network != "none" else self.build


class TestSandbox(BuildSandbox):
    """A `BuildSandbox` whose test job answers `tested` and records what it was asked."""

    __test__ = False

    def __init__(self, modules: Mapping[str, Mapping[str, str]], tested: ExecResult, **kw: object):
        super().__init__(modules, **kw)  # type: ignore[arg-type]
        self.tested = tested
        self.test_jobs: list[tuple[JobNetwork, str]] = []

    async def run_job(
        self,
        argv: Sequence[str],
        *,
        network: JobNetwork,
        cwd: str,
        timeout_s: float,
        env: Mapping[str, str] | None = None,
    ) -> ExecResult:
        if len(argv) > 3 and argv[3] == "test":
            self.test_jobs.append((network, argv[2]))
            return self.tested
        return await super().run_job(argv, network=network, cwd=cwd, timeout_s=timeout_s, env=env)


def node_module(test: str | None = "jest", build: bool = False) -> dict[str, str]:
    scripts: dict[str, str] = {"build": "tsc"} if build else {}
    if test:
        scripts["test"] = test
    return {"package.json": json.dumps({"scripts": scripts}), "package-lock.json": "{}"}


PY = {"pyproject.toml": PYPROJECT + '\n[dependency-groups]\ndev = ["pytest"]\n', "uv.lock": "x"}


async def test_a_passing_node_module_reports_its_counts() -> None:
    box = TestSandbox({".": node_module()}, ExecResult(0, "Tests:       3 passed, 3 total\n", ""))

    report = await run_tests(box, ".", ("node",))  # type: ignore[arg-type]

    [check] = report.checks
    assert (check.status, check.runner, check.passed, check.failed) == ("passed", "jest", 3, 0)
    assert check.reason is None
    assert box.test_jobs == [("none", "CI=true npm test\n")]  # no network for the tests


async def test_a_failing_node_module_names_the_test_and_counts() -> None:
    box = TestSandbox({".": node_module()}, ExecResult(1, JEST_FAIL, ""))

    [check] = (await run_tests(box, ".", ("node",))).checks  # type: ignore[arg-type]

    assert (check.status, check.reason) == ("failed", "tests failed (1 of 3)")
    assert [f.name for f in check.failures] == ["sum › adds"]
    assert check.failures[0].file == "src/sum.test.js"
    assert "Expected: 3" in (check.failures[0].message or "")


async def test_a_module_that_does_not_build_is_not_tested() -> None:
    box = TestSandbox(
        {".": node_module(build=True)},
        ExecResult(0, "", ""),
        build=ExecResult(2, "", "tsc: error TS2304 in secret.ts"),
    )

    [check] = (await run_tests(box, ".", ("node",))).checks  # type: ignore[arg-type]

    assert (check.status, check.reason, check.build) == ("failed", "does not build", "failed")
    assert box.test_jobs == []
    assert "secret" not in check.model_dump_json()


async def test_a_module_with_no_test_script_or_the_npm_placeholder_has_no_tests() -> None:
    for script in (None, 'echo "Error: no test specified" && exit 1'):
        box = TestSandbox({".": node_module(test=script)}, ExecResult(0, "", ""))

        [check] = (await run_tests(box, ".", ("node",))).checks  # type: ignore[arg-type]

        assert (check.status, check.reason) == ("skipped", "no tests found")
        assert box.test_jobs == []


async def test_a_restore_that_fails_is_an_error_with_the_restores_reason() -> None:
    box = TestSandbox(
        {".": node_module()}, ExecResult(0, "", ""), restore=ExecResult(1, "E404", "")
    )

    [check] = (await run_tests(box, ".", ("node",))).checks  # type: ignore[arg-type]

    assert (check.status, check.reason) == ("error", "restore failed: a package is not on npm")


async def test_a_test_run_that_times_out_is_an_error() -> None:
    box = TestSandbox({".": node_module()}, ExecResult(124, "", ""))

    [check] = (await run_tests(box, ".", ("node",))).checks  # type: ignore[arg-type]

    assert (check.status, check.reason) == ("error", "test run timed out")


async def test_python_runs_pytest_and_reads_the_junit_file() -> None:
    out = f"F.s\n{JUNIT_MARKER}\n{JUNIT}"
    box = TestSandbox({".": PY}, ExecResult(1, out, ""))

    [check] = (await run_tests(box, ".", ("python",))).checks  # type: ignore[arg-type]

    assert (check.status, check.runner, check.reason) == (
        "failed",
        "pytest",
        "tests failed (1 of 3)",
    )
    assert (check.passed, check.failed, check.skipped) == (1, 1, 1)
    assert [f.name for f in check.failures] == ["tests.test_sum::test_adds"]
    assert check.failures[0].message == "assert 4 == 3"
    assert ".venv/bin/python -m pytest" in box.test_jobs[0][1]


async def test_python_without_pytest_has_no_supported_runner() -> None:
    box = TestSandbox({".": {"pyproject.toml": PYPROJECT, "uv.lock": "x"}}, ExecResult(0, "", ""))

    [check] = (await run_tests(box, ".", ("python",))).checks  # type: ignore[arg-type]

    assert (check.status, check.reason) == ("skipped", "no supported test runner for python")
    assert box.test_jobs == []


async def test_pytest_finding_nothing_is_no_tests_and_a_crash_is_an_error() -> None:
    none = TestSandbox({".": PY}, ExecResult(5, f"{JUNIT_MARKER}\n", ""))
    crash = TestSandbox({".": PY}, ExecResult(2, "", ""))

    [empty] = (await run_tests(none, ".", ("python",))).checks  # type: ignore[arg-type]
    [broken] = (await run_tests(crash, ".", ("python",))).checks  # type: ignore[arg-type]

    assert (empty.status, empty.reason) == ("skipped", "no tests found")
    assert (broken.status, broken.reason) == ("error", "test run failed")


async def test_the_report_counts_checks_by_status() -> None:
    box = TestSandbox({".": node_module()}, ExecResult(1, JEST_FAIL, ""))

    report = await run_tests(box, ".", ("node",), BuildLimits())  # type: ignore[arg-type]

    assert report.counts == {"passed": 0, "failed": 1, "skipped": 0, "error": 0}
    assert report.tool == "build.test"


def test_each_node_runner_summary_is_read() -> None:
    for runner, text in (
        ("vitest", VITEST_FAIL),
        ("node:test", NODE_SPEC),
        ("node:test", NODE_TAP),
        ("jest", JEST_FAIL),
    ):
        outcome = parse_node_output(runner, text)
        assert outcome is not None, text
        assert (outcome.passed, outcome.failed, outcome.total) == (2, 1, 3), text
        assert [f.name for f in outcome.failures][:1] == [
            "sum > adds" if runner == "vitest" else ("sum › adds" if runner == "jest" else "adds")
        ], text


def test_ansi_colours_do_not_hide_a_summary() -> None:
    outcome = parse_node_output("jest", "\x1b[1mTests:\x1b[22m       2 passed, 2 total\n")

    assert outcome is not None and (outcome.passed, outcome.total) == (2, 2)


def test_failures_and_messages_are_capped() -> None:
    cases = "".join(
        f'<testcase classname="t" name="n{i}"><failure message="{"x" * 2000}"/></testcase>'
        for i in range(MAX_FAILURES + 10)
    )

    outcome = parse_junit(f"<testsuite>{cases}</testsuite>")

    assert outcome is not None
    assert outcome.failed == MAX_FAILURES + 10  # counted in full
    assert len(outcome.failures) == MAX_FAILURES
    assert all(len(f.message or "") <= MAX_MESSAGE for f in outcome.failures)


def test_a_junit_file_with_entities_is_refused() -> None:
    bomb = '<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite><testcase name="&a;"/></testsuite>'

    assert parse_junit(bomb) is None
    assert parse_junit("not xml") is None


# --- 13.4: cases, coverage of the changed lines, the base run -------------------------------------

CRITERIA_JUNIT = """<testsuites><testsuite tests="2">
<testcase classname="tests.test_t" name="test_ac_001_ok"/>
<testcase classname="tests.test_t" name="test_other"/>
</testsuite></testsuites>"""
COVERAGE_JSON = json.dumps(
    {"meta": {"v": 1}, "files": {"a.py": {"executed_lines": [1, 2], "missing_lines": [3, 4]}}}
)


async def test_python_reports_cases_and_coverage_of_the_changed_lines() -> None:
    out = f"..\n::coverage::\n{COVERAGE_JSON}\n{JUNIT_MARKER}\n{CRITERIA_JUNIT}"
    box = TestSandbox({".": PY}, ExecResult(0, out, ""))
    options = TestOptions(select=("AC-001", "AC-002"), coverage=True, changes={"a.py": {2, 3, 4}})

    [check] = (await run_tests(box, ".", ("python",), options=options)).checks  # type: ignore[arg-type]

    assert [(c.name, c.status, c.ids) for c in check.cases] == [
        ("tests.test_t::test_ac_001_ok", "passed", ["AC-001"])
    ]
    assert check.coverage is not None
    assert (check.coverage.changed, check.coverage.covered) == (3, 1)
    assert check.coverage.files[0].uncovered == [(3, 4)]
    assert check.coverage_reason is None
    assert "coverage run" in box.test_jobs[0][1]  # the coverage script ran, with no network
    assert box.test_jobs[0][0] == "none"


async def test_coverage_that_cannot_be_read_says_so() -> None:
    out = f"..\n::coverage::\nnot json\n{JUNIT_MARKER}\n{CRITERIA_JUNIT}"
    box = TestSandbox({".": PY}, ExecResult(0, out, ""))

    [check] = (
        await run_tests(box, ".", ("python",), options=TestOptions(coverage=True))  # type: ignore[arg-type]
    ).checks

    assert check.coverage is None
    assert check.coverage_reason == "coverage could not be measured"


async def test_the_base_run_selects_by_id_and_a_missing_result_is_not_an_error() -> None:
    box = TestSandbox({".": PY}, ExecResult(1, f"{JUNIT_MARKER}\n{CRITERIA_JUNIT}", ""))
    options = TestOptions(select=("AC-001",), base=True)

    [check] = (await run_tests(box, ".", ("python",), options=options)).checks  # type: ignore[arg-type]

    assert [c.ids for c in check.cases] == [["AC-001"]]
    assert "-k" in box.test_jobs[0][1]
    assert check.coverage is None


async def test_a_base_run_that_leaves_no_junit_file_is_an_error_not_a_pass() -> None:
    box = TestSandbox({".": PY}, ExecResult(2, "", ""))

    [check] = (
        await run_tests(box, ".", ("python",), options=TestOptions(select=("AC-001",), base=True))  # type: ignore[arg-type]
    ).checks

    assert (check.status, check.reason) == ("error", "test run failed")


async def test_node_gives_fixed_reasons_for_coverage_and_per_test_results() -> None:
    box = TestSandbox({".": node_module()}, ExecResult(0, "Tests:       3 passed, 3 total\n", ""))
    options = TestOptions(select=("AC-001",), coverage=True)

    [check] = (await run_tests(box, ".", ("node",), options=options)).checks  # type: ignore[arg-type]

    assert check.status == "passed"
    assert check.coverage is None and check.cases == []
    assert check.coverage_reason == "coverage is not measured for node yet"
    assert check.cases_reason == "per-test results are not read for node yet"
