from pathlib import Path

from sync_roadmap_board import MARKER, TITLE_LIMIT, issue_body, issue_title, parse_roadmap

ROADMAP = """\
# Roadmap

Intro text that belongs to no milestone.

---

## Milestone 0: Walking skeleton

| # | Phase | Done when | Status |
|---|---|---|---|
| 0.1 | Repo scaffold | CI is green | ✅ Done ([#1](https://example.test/pull/1)) |
| 0.2 | Workflow spec v0 | A sample spec validates | ✅ Done ([#3](https://example.test/pull/3)) |

## Milestone 2: Product UI foundation

The UI comes first.
It spans two lines.

| # | Phase | Done when | Status |
|---|---|---|---|
| 2.1 | Design system | axe finds no serious issues | — |

---

## Acceptance criteria map

| AC | Phase |
|---|---|
| AC-1 Docs run opens PR | 1.11 |
"""


def test_parse_roadmap_reads_milestones_and_phases() -> None:
    milestones = parse_roadmap(ROADMAP)
    assert [m.name for m in milestones] == [
        "Milestone 0: Walking skeleton",
        "Milestone 2: Product UI foundation",
    ]
    assert [p.number for p in milestones[0].phases] == ["0.1", "0.2"]
    assert milestones[0].description == ""
    assert milestones[1].description == "The UI comes first. It spans two lines."
    assert milestones[0].done and not milestones[1].done
    assert milestones[0].phases[1].pr == "3"
    assert milestones[1].phases[0].pr is None


def test_issue_body_has_the_marker_and_status() -> None:
    milestone = parse_roadmap(ROADMAP)[0]
    body = issue_body(milestone.phases[0], milestone, "o/r")
    match = MARKER.search(body)
    assert match is not None and match.group(1) == "0.1"
    assert "Done in #1" in body
    assert "CI is green" in body


def test_long_titles_are_cut() -> None:
    milestone = parse_roadmap(ROADMAP)[1]
    phase = milestone.phases[0]
    phase.title = "x" * 300
    assert len(issue_title(phase)) == TITLE_LIMIT
    assert issue_title(phase).endswith("…")


def test_real_roadmap_parses() -> None:
    roadmap = Path(__file__).parent.parent / "specs" / "roadmap.md"
    milestones = parse_roadmap(roadmap.read_text(encoding="utf-8"))
    # Milestones are listed in the order they are worked, not by number.
    assert sorted(m.number for m in milestones) == list(range(len(milestones)))
    assert all(m.phases for m in milestones)
    phases = [p.number for m in milestones for p in m.phases]
    assert len(phases) == len(set(phases))
