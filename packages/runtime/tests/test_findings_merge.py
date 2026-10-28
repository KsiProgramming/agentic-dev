"""`merge_reports`: the deterministic merge behind the `dedupe` and `vote` reduces (4.5)."""

from typing import Any

import pytest

from agentic_runtime.findings import (
    Check,
    Finding,
    FindingsReport,
    VoteError,
    build_report,
    fingerprint,
    merge_reports,
)


def _finding(**fields: Any) -> Finding:
    base: dict[str, Any] = {
        "fingerprint": "fp-a",
        "tool": "ruff",
        "rule": "F401",
        "severity": "low",
        "category": "lint",
        "path": "app.py",
        "line": 3,
        "message": "unused import",
    }
    return Finding.model_validate(base | fields)


def _report(*findings: Finding, **fields: Any) -> FindingsReport:
    check = Check(path=".", kind="python", tool="ruff", status="ran", findings=len(findings))
    report = build_report("lint", [check], findings)
    return report.model_copy(update=fields)


def test_the_same_fingerprint_from_two_sources_is_one_finding() -> None:
    merged = merge_reports([("lint", _report(_finding())), ("review", _report(_finding()))])

    assert merged.findings_in == 2
    [finding] = merged.report.findings
    assert finding.sources == ["lint", "review"]
    assert finding.confidence == 1.0
    assert merged.report.scanner == "merged"


def test_findings_without_a_fingerprint_merge_by_category_path_line_and_rule() -> None:
    a = _finding(fingerprint=None, rule="no unused  imports")
    b = _finding(fingerprint=None, rule="no unused imports", tool="agent")
    other_line = _finding(fingerprint=None, rule="no unused imports", line=4)

    merged = merge_reports([("a", _report(a)), ("b", _report(b, other_line))])

    assert [f.sources for f in merged.report.findings] == [["a", "b"], ["b"]]
    expected = fingerprint("lint", "app.py", 3, "no unused imports")
    assert merged.report.findings[0].fingerprint == expected


def test_the_highest_severity_wins_from_the_first_source_that_gave_it() -> None:
    low = _finding(severity="low", message="from lint")
    high = _finding(severity="high", message="from review")
    also_high = _finding(severity="high", message="from third")

    merged = merge_reports(
        [("lint", _report(low)), ("review", _report(high)), ("x", _report(also_high))]
    )

    [finding] = merged.report.findings
    assert (finding.severity, finding.message) == ("high", "from review")


def test_lists_are_unioned_and_the_repo_config_wins() -> None:
    a = _finding(aliases=["CVE-1"], fixed_versions=["2.0"], config="platform-default")
    b = _finding(
        aliases=["CVE-2", "CVE-1"], fixed_versions=["2.1"], help_url="https://x", config="repo"
    )

    [finding] = merge_reports([("a", _report(a)), ("b", _report(b))]).report.findings

    assert finding.aliases == ["CVE-1", "CVE-2"]
    assert finding.fixed_versions == ["2.0", "2.1"]
    assert finding.help_url == "https://x"
    assert finding.config == "repo"


def test_confidence_is_the_share_of_sources_times_their_own() -> None:
    merged = merge_reports(
        [
            ("a", _report(_finding(confidence=0.5))),
            ("b", _report(_finding())),
            ("c", _report(_finding(fingerprint="fp-b"))),
        ]
    )

    by_fp = {f.fingerprint: f.confidence for f in merged.report.findings}
    assert by_fp == {"fp-a": round(2 / 3 * 0.75, 2), "fp-b": 0.33}


def test_a_source_reporting_an_issue_twice_counts_once() -> None:
    merged = merge_reports([("a", _report(_finding(), _finding())), ("b", _report())])

    [finding] = merged.report.findings
    assert finding.sources == ["a"]
    assert finding.confidence == 0.5


def test_vote_keeps_what_enough_sources_reported() -> None:
    sources = [
        ("a", _report(_finding(), _finding(fingerprint="only-a"))),
        ("b", _report(_finding())),
        ("c", _report()),
    ]

    merged = merge_reports(sources, min_votes=2)

    assert [f.fingerprint for f in merged.report.findings] == ["fp-a"]
    assert merged.report.counts["low"] == 1


def test_vote_with_too_few_sources_fails() -> None:
    with pytest.raises(VoteError, match="needs 2 sources, 1 completed"):
        merge_reports([("a", _report(_finding()))], min_votes=2)


def test_order_counts_cap_and_report_fields() -> None:
    findings = [_finding(fingerprint=f"fp-{i}", line=i) for i in range(5)]
    deps = _report(
        _finding(fingerprint="dep", severity="critical", category="dependency"),
        db_as_of="2026-10-20",
    ).model_copy(update={"scanner": "dependencies"})
    lint = _report(*findings, db_as_of="2026-10-28", truncated=True)

    merged = merge_reports([("lint", lint), ("deps", deps)], max_findings=3)
    report = merged.report

    assert [f.fingerprint for f in report.findings] == ["dep", "fp-0", "fp-1"]
    assert report.counts == {"critical": 1, "high": 0, "medium": 0, "low": 5, "info": 0}
    assert report.truncated
    assert report.db_as_of == "2026-10-20"
    assert len(report.checks) == 2
    assert [(s.id, s.scanner, s.findings) for s in report.sources or []] == [
        ("lint", "lint", 5),
        ("deps", "dependencies", 1),
    ]


def test_more_confident_findings_come_first_within_a_severity() -> None:
    merged = merge_reports(
        [
            (
                "a",
                _report(
                    _finding(fingerprint="z", path="a.py"), _finding(fingerprint="y", path="b.py")
                ),
            ),
            ("b", _report(_finding(fingerprint="y", path="b.py"))),
        ]
    )

    assert [f.fingerprint for f in merged.report.findings] == ["y", "z"]


def test_sources_without_findings_give_an_empty_report() -> None:
    merged = merge_reports([("a", _report()), ("b", _report())])

    assert merged.report.findings == []
    assert merged.findings_in == 0
    assert [s.id for s in merged.report.sources or []] == ["a", "b"]
    assert not merged.report.truncated


def test_the_merge_is_deterministic() -> None:
    sources = [("a", _report(_finding(), _finding(fingerprint="b"))), ("b", _report(_finding()))]

    first = merge_reports(sources).report.model_dump_json()

    assert merge_reports(sources).report.model_dump_json() == first
