# ruff: noqa: E501
"""Criterion ids, per-test results and the coverage of changed lines (13.4), on shaped input. The real
jobs run in `test_build_docker.py`."""

import json

import pytest

from agentic_tools.build.changed import (
    changed_coverage,
    is_test_path,
    merge_coverage,
    parse_cobertura,
    parse_coverage_json,
    parse_patch,
    ranges,
    source_changes,
)
from agentic_tools.build.dotnet_test import split_cobertura
from agentic_tools.build.dotnet_test import test_script as dotnet_script
from agentic_tools.build.tests import (
    MAX_COVERED_FILES,
    MAX_RANGES,
    TestOptions,
    criterion_ids,
    is_criterion_id,
    parse_junit,
    parse_trx,
    python_script,
    split_coverage,
)


@pytest.mark.parametrize(
    ("name", "ids"),
    [
        ("test_ac_001_rejects_empty_title", ["AC-001"]),
        ("tests.test_x::test_AC001_works", ["AC-001"]),
        ("AC001_RejectsEmptyTitle", ["AC-001"]),
        ('Ns.Titles.ac_002_x(title: "a")', ["AC-002"]),
        ("test_title[AC-001]", ["AC-001"]),
        ("test_ac_001_and_ac_002", ["AC-001", "AC-002"]),
        ("test_ac_001_ac_001", ["AC-001"]),
        ("test_TRACK001_is_not_one", []),
        ("test_ac_0011_is_a_longer_number", ["AC-0011"]),
        ("test_abc_001", []),
        ("test_ac_12", []),
    ],
)
def test_criterion_ids(name: str, ids: list[str]) -> None:
    assert criterion_ids(name) == ids


def test_only_well_formed_ids_are_selectable() -> None:
    assert is_criterion_id("AC-001")
    assert not any(is_criterion_id(t) for t in ("AC-1", "ac-001", "AC-001; rm -rf /", "AC-001\n"))


JUNIT = """<testsuites><testsuite tests="4">
<testcase classname="tests.test_t" name="test_ac_001_ok"/>
<testcase classname="tests.test_t" name="test_ac_002_bad"><failure message="x">tb</failure></testcase>
<testcase classname="tests.test_t" name="test_other"/>
<testcase classname="" name="tests.test_new"><error message="collection failure">Import</error></testcase>
</testsuite></testsuites>"""


def test_junit_keeps_every_test_that_names_a_criterion() -> None:
    outcome = parse_junit(JUNIT)

    assert outcome is not None
    assert [(c.name, c.status, c.ids) for c in outcome.cases] == [
        ("tests.test_t::test_ac_001_ok", "passed", ["AC-001"]),
        ("tests.test_t::test_ac_002_bad", "failed", ["AC-002"]),
    ]
    assert outcome.cases[0].file == "tests/test_t.py"


TRX = """<?xml version="1.0"?><TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
<Results>
<UnitTestResult testId="1" testName="AC001_Rejects" outcome="Passed"/>
<UnitTestResult testId="2" testName="AC002_Fails" outcome="Failed"><Output><ErrorInfo><Message>no</Message></ErrorInfo></Output></UnitTestResult>
<UnitTestResult testId="3" testName="AC003_Skipped" outcome="NotExecuted"/>
</Results>
<TestDefinitions>
<UnitTest id="1"><TestMethod className="App.Tests.Titles"/></UnitTest>
</TestDefinitions></TestRun>"""


def test_trx_keeps_every_test_that_names_a_criterion() -> None:
    outcome = parse_trx([TRX])

    assert outcome is not None
    assert [(c.name, c.status) for c in outcome.cases] == [
        ("AC001_Rejects", "passed"),
        ("AC002_Fails", "failed"),
        ("AC003_Skipped", "skipped"),
    ]
    assert outcome.cases[0].file == "App.Tests.Titles"


PATCH = """\
diff --git a/src/a.py b/src/a.py
index 1..2 100644
--- a/src/a.py
+++ b/src/a.py
@@ -3 +3,2 @@ def f():
-old
+new
+newer
@@ -10,2 +11,0 @@ def g():
-gone
-gone2
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x
-y
diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -0,0 +1,4 @@
+def test_ac_001(): ...
diff --git a/pkg/new name.py b/pkg/renamed.py
similarity index 90%
rename from pkg/new name.py
rename to pkg/renamed.py
--- a/pkg/new name.py
+++ b/pkg/renamed.py
@@ -5 +5 @@
-a
+b
"""


def test_added_and_modified_lines_are_the_new_side_of_each_hunk() -> None:
    changed = parse_patch(PATCH)

    assert changed["src/a.py"] == {3, 4}  # a pure deletion (+11,0) adds none
    assert changed["pkg/renamed.py"] == {5}
    assert "old.py" not in changed  # a deleted file has no new lines


def test_test_files_and_other_directories_are_left_out() -> None:
    assert set(source_changes(PATCH)) == {"src/a.py", "pkg/renamed.py"}
    assert set(source_changes(PATCH, "src")) == {"src/a.py"}


@pytest.mark.parametrize(
    "path",
    [
        "tests/x.py",
        "pkg/test_x.py",
        "pkg/x_test.py",
        "conftest.py",
        "web/a.spec.ts",
        "App.Tests/X.cs",
        "src/__tests__/a.js",
        "src/XTests.cs",
    ],
)
def test_paths_that_are_tests(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize("path", ["src/a.py", "pkg/latest.py", "contest/x.py", "Program.cs"])
def test_paths_that_are_not_tests(path: str) -> None:
    assert not is_test_path(path)


def coverage_json(**files: tuple[list[int], list[int]]) -> str:
    return json.dumps(
        {
            "meta": {"version": "7"},
            "files": {f: {"executed_lines": e, "missing_lines": m} for f, (e, m) in files.items()},
        }
    )


def test_coverage_is_the_share_of_changed_executable_lines_the_tests_ran() -> None:
    report = parse_coverage_json(coverage_json(**{"a.py": ([1, 2, 5, 6], [7, 8, 9])}))
    assert report is not None

    # 2 is covered, 7 and 8 are not, 3 is a comment (not executable), 40 is not in the file.
    result = changed_coverage({"a.py": {2, 3, 7, 8, 40}}, report)

    assert (result.changed, result.covered) == (3, 1)
    [file] = result.files
    assert (file.path, file.changed, file.covered, file.uncovered) == ("a.py", 3, 1, [(7, 8)])


def test_a_change_with_no_executable_lines_has_nothing_to_cover() -> None:
    report = parse_coverage_json(coverage_json(**{"a.py": ([1], [2])}))
    assert report is not None

    result = changed_coverage({"a.py": {10}, "README.md": {1}}, report)

    assert (result.changed, result.covered, result.files) == (0, 0, [])


def test_a_module_reads_its_files_relative_to_itself() -> None:
    report = parse_coverage_json(coverage_json(**{"pkg/a.py": ([1], [2])}))
    assert report is not None

    result = changed_coverage({"mod/pkg/a.py": {1, 2}, "other/pkg/a.py": {2}}, report, prefix="mod")

    assert (result.changed, result.covered) == (2, 1)
    assert result.files[0].path == "mod/pkg/a.py"


def test_coverage_json_that_is_not_one_is_refused() -> None:
    assert parse_coverage_json("not json") is None
    assert parse_coverage_json("{}") is None


COBERTURA = """<?xml version="1.0"?><coverage><packages><package><classes>
<class filename="/work/src/Titles.cs"><lines>
<line number="10" hits="3"/><line number="11" hits="0"/><line number="12" hits="0"/>
</lines></class></classes></package></packages></coverage>"""


def test_cobertura_is_read_and_matched_by_the_end_of_its_absolute_paths() -> None:
    report = parse_cobertura(COBERTURA)
    assert report is not None

    result = changed_coverage(
        {"src/Titles.cs": {10, 11, 12, 13}}, {"/work/src/Titles.cs": report["/work/src/Titles.cs"]}
    )

    assert (result.changed, result.covered) == (3, 1)
    assert result.files[0].uncovered == [(11, 12)]


def test_a_cobertura_with_entities_is_refused() -> None:
    assert parse_cobertura('<!DOCTYPE x [<!ENTITY a "b">]><coverage/>') is None
    assert parse_cobertura("<other/>") is None


def test_lines_make_ranges() -> None:
    assert ranges([5, 1, 2, 3, 9, 10, 2]) == [(1, 3), (5, 5), (9, 10)]


def test_files_and_ranges_are_capped() -> None:
    many = {f"f{i:03}.py": set(range(1, 100, 2)) for i in range(MAX_COVERED_FILES + 5)}
    report = parse_coverage_json(
        coverage_json(**{f: (list(range(2, 100, 2)), list(range(1, 100, 2))) for f in many})
    )
    assert report is not None

    result = changed_coverage(many, report)

    assert len(result.files) == MAX_COVERED_FILES
    assert result.truncated
    assert all(len(f.uncovered) <= MAX_RANGES for f in result.files)
    assert merge_coverage([result, result]).changed == 2 * result.changed


def test_the_python_job_prints_coverage_before_the_junit_file() -> None:
    script = python_script(TestOptions(coverage=True))
    assert script.index("::coverage::") < script.index("::junit::")
    head, report = split_coverage('out\n::coverage::\n{"meta": 1}\n')
    assert (head, report) == ("out\n", '{"meta": 1}\n')
    assert "-k" in python_script(TestOptions(base=True, select=("AC-001",)))
    assert python_script() == python_script(TestOptions())


def test_the_dotnet_job_prints_cobertura_before_the_trx_files() -> None:
    script = dotnet_script(TestOptions(coverage=True))
    assert script.index("::cobertura::") < script.index("::trx::")
    assert "Format=cobertura" in script
    assert "--filter" in dotnet_script(TestOptions(base=True))
    output = f"x\n::cobertura::\n{COBERTURA}\n::trx::\n"
    assert len(split_cobertura(output)) == 1
