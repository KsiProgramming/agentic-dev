from check_roadmap import changed_spec_dirs, mark_done, phase_of, phase_statuses, problems

ROADMAP = """\
| # | Phase | Done when | Status |
|---|---|---|---|
| 0.1 | Repo scaffold | CI is green | ✅ Done ([#1](https://example.test/pull/1)) |
| 0.2 | Workflow spec v0 | A sample spec validates | — |
| 1.10 | `map` + `reduce` | Map over 3 modules | — |

| AC | Phase |
|---|---|
| AC-1 Docs run opens PR | 1.11 |
"""


def test_changed_spec_dirs_ignores_other_paths() -> None:
    paths = [
        "specs/2026-10-21-repo-scaffold/plan.md",
        "specs/2026-10-21-repo-scaffold/requirements.md",
        "specs/roadmap.md",
        "packages/api/src/agentic_api/app.py",
    ]

    assert changed_spec_dirs(paths) == {"2026-10-21-repo-scaffold"}


def test_phase_of_reads_roadmap_phase_line() -> None:
    assert phase_of("# Title\n\nRoadmap phase: 1.10\nBranch: x\n") == "1.10"
    assert phase_of("# Title\n") is None


def test_phase_statuses_reads_only_phase_rows() -> None:
    statuses = phase_statuses(ROADMAP)

    assert statuses == {
        "0.1": "✅ Done ([#1](https://example.test/pull/1))",
        "0.2": "—",
        "1.10": "—",
    }


def test_done_phase_passes() -> None:
    assert problems({"0.1"}, ROADMAP) == []


def test_not_done_or_unknown_phase_fails() -> None:
    errors = problems({"0.2", "9.9"}, ROADMAP)

    assert len(errors) == 2
    assert "Phase 0.2 is implemented by this PR" in errors[0]
    assert "Phase 9.9 is not in" in errors[1]


def test_mark_done_sets_status_with_pr_link() -> None:
    url = "https://example.test/pull/7"
    roadmap, changed = mark_done({"0.2", "1.10"}, ROADMAP, url)

    assert changed == ["0.2", "1.10"]
    assert phase_statuses(roadmap)["0.2"] == f"✅ Done ([#7]({url}))"
    assert phase_statuses(roadmap)["1.10"] == f"✅ Done ([#7]({url}))"
    assert "| 0.2 | Workflow spec v0 | A sample spec validates | ✅ Done" in roadmap
    assert problems({"0.2", "1.10"}, roadmap) == []


def test_mark_done_keeps_done_phases_and_other_lines() -> None:
    roadmap, changed = mark_done({"0.1"}, ROADMAP, "https://example.test/pull/7")

    assert changed == []
    assert roadmap == ROADMAP
