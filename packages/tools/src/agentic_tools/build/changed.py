"""Coverage of the lines a change touched (13.4).

The change's lines come from `git diff -U0` against the run's base (`parse_patch`), test files left
out (`is_test_path`). The coverage report comes from the runner (coverage.py's JSON for Python,
Cobertura XML for .NET) and says, per file, which lines are executable and which the tests ran.
`changed_coverage` intersects the two, so the number is the share of the *changed executable lines*
the tests ran, never the repo's coverage. Reports and diffs are written by or about repo content:
a document with a DTD or entities is refused, and everything that leaves is counts, paths and line
ranges, capped.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping

from agentic_tools.build.stack import as_list, as_table
from agentic_tools.build.tests import (
    MAX_COVERED_FILES,
    MAX_RANGES,
    ChangedCoverage,
    CoveredFile,
)

type Lines = tuple[set[int], set[int]]
"""A file's executable lines and, of those, the ones the tests ran."""

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs", "e2e", "testing"})
_TEST_NAME = re.compile(
    r"(^test_.*\.py$|_test\.py$|^conftest\.py$|\.(test|spec)\.[cm]?[jt]sx?$|Tests?\.cs$)"
)


def is_test_path(path: str) -> bool:
    """Whether a repo-relative path is a test file: in a test directory (`tests/`, `__tests__/`,
    a `*.Tests` or `*.Test` project), or named like one (`test_x.py`, `x_test.py`, `x.spec.ts`,
    `XTests.cs`, `conftest.py`)."""
    *directories, name = path.split("/")
    if any(
        d.lower() in _TEST_DIRS or re.search(r"\.tests?$", d, re.IGNORECASE) for d in directories
    ):
        return True
    return _TEST_NAME.search(name) is not None


def parse_patch(diff: str) -> dict[str, set[int]]:
    """The lines a `git diff -U0` adds or modifies, by new path: the new side of every hunk. A
    deleted file has no new lines, a renamed one is read at its new path."""
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].split("\t")[0]
            current = name[2:] if name.startswith("b/") else None
            if current is not None:
                changed.setdefault(current, set())
        elif current is not None and (hunk := _HUNK.match(line)):
            start = int(hunk.group(1))
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            changed[current].update(range(start, start + count))
    return {path: lines for path, lines in changed.items() if lines}


def source_changes(diff: str, under: str = ".") -> dict[str, set[int]]:
    """`parse_patch` without test files, and only the paths at or under the directory `under`."""
    prefix = "" if under == "." else f"{under.rstrip('/')}/"
    return {
        path: lines
        for path, lines in parse_patch(diff).items()
        if path.startswith(prefix) and not is_test_path(path)
    }


def parse_coverage_json(text: str) -> dict[str, Lines] | None:
    """coverage.py's `coverage json` as executable and covered lines per file, or None when it is
    not one. A line is executable when it was run or missed."""
    try:
        data = as_table(json.loads(text))
    except ValueError:
        return None
    files = as_table(data.get("files"))
    if "meta" not in data or not files:
        return None if "meta" not in data else {}
    found: dict[str, Lines] = {}
    for name, entry in files.items():
        table = as_table(entry)
        ran = {n for n in as_list(table.get("executed_lines")) if isinstance(n, int)}
        missed = {n for n in as_list(table.get("missing_lines")) if isinstance(n, int)}
        found[name] = (ran | missed, ran)
    return found


def parse_cobertura(text: str) -> dict[str, Lines] | None:
    """A Cobertura XML report as executable and covered lines per file, or None when it is not one
    (or has a DTD or entities)."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        root = ET.fromstring(text.strip().lstrip("﻿"))
    except ET.ParseError:
        return None
    if root.tag != "coverage":
        return None
    found: dict[str, tuple[set[int], set[int]]] = {}
    for cls in root.iter("class"):
        name = cls.get("filename")
        if not name:
            continue
        executable, ran = found.setdefault(name.replace("\\", "/"), (set(), set()))
        for line in cls.iter("line"):
            number, hits = line.get("number", ""), line.get("hits", "0")
            if number.isdigit():
                executable.add(int(number))
                if hits.isdigit() and int(hits) > 0:
                    ran.add(int(number))
    return found


def ranges(lines: Iterable[int]) -> list[tuple[int, int]]:
    """Sorted lines as inclusive ranges of consecutive ones."""
    out: list[tuple[int, int]] = []
    for n in sorted(set(lines)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def _lookup(report: Mapping[str, Lines], path: str) -> Lines | None:
    if path in report:
        return report[path]
    suffix = f"/{path}"
    return next((lines for name, lines in report.items() if name.endswith(suffix)), None)


def changed_coverage(
    changes: Mapping[str, set[int]], report: Mapping[str, Lines], *, prefix: str = ""
) -> ChangedCoverage:
    """The coverage of `changes` (new lines by repo path) from `report`. `prefix` is the module's
    directory, which the report's paths are relative to (`""` for the repo root). A changed file
    the report does not list, or a changed line that is not executable, counts for nothing."""
    files: list[CoveredFile] = []
    total = covered = 0
    for path in sorted(changes):
        if prefix and not path.startswith(f"{prefix}/"):
            continue
        listed = _lookup(report, path[len(prefix) + 1 :] if prefix else path)
        if listed is None:
            continue
        executable, ran = listed
        touched = changes[path] & executable
        if not touched:
            continue
        missed = touched - ran
        total += len(touched)
        covered += len(touched) - len(missed)
        files.append(
            CoveredFile(
                path=path,
                changed=len(touched),
                covered=len(touched) - len(missed),
                uncovered=ranges(missed)[:MAX_RANGES],
            )
        )
    return ChangedCoverage(
        changed=total,
        covered=covered,
        files=files[:MAX_COVERED_FILES],
        truncated=len(files) > MAX_COVERED_FILES,
    )


def merge_coverage(parts: Iterable[ChangedCoverage]) -> ChangedCoverage:
    """The coverage of several modules as one: counts added, files kept up to the cap."""
    files: list[CoveredFile] = []
    changed = covered = 0
    truncated = False
    for part in parts:
        changed += part.changed
        covered += part.covered
        files.extend(part.files)
        truncated = truncated or part.truncated
    return ChangedCoverage(
        changed=changed,
        covered=covered,
        files=files[:MAX_COVERED_FILES],
        truncated=truncated or len(files) > MAX_COVERED_FILES,
    )
