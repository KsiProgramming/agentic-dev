"""Fail a PR that implements a roadmap phase without marking it done in specs/roadmap.md.

A PR implements a phase when it touches a spec folder (specs/<date>-<slug>/) whose
requirements.md has a `Roadmap phase: <number>` line. That phase's row in
specs/roadmap.md must then have a Status cell starting with "✅ Done".

Usage: python scripts/check_roadmap.py <base-sha> <head-sha>
"""

import io
import re
import subprocess
import sys

ROADMAP = "specs/roadmap.md"
SPEC_DIR = re.compile(r"^specs/(\d{4}-\d{2}-\d{2}-[^/]+)/")
PHASE_LINE = re.compile(r"^Roadmap phase:\s*(\d+\.\d+)\s*$", re.MULTILINE)
PHASE_ROW = re.compile(r"^\|\s*(\d+\.\d+)\s*\|")
DONE_PREFIX = "✅ Done"


def changed_spec_dirs(paths: list[str]) -> set[str]:
    return {m.group(1) for p in paths if (m := SPEC_DIR.match(p))}


def phase_of(requirements: str) -> str | None:
    match = PHASE_LINE.search(requirements)
    return match.group(1) if match else None


def phase_statuses(roadmap: str) -> dict[str, str]:
    """Map phase number to its Status cell (the last column of the row)."""
    statuses: dict[str, str] = {}
    for line in roadmap.splitlines():
        if match := PHASE_ROW.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            statuses[match.group(1)] = cells[-1]
    return statuses


def problems(phases: set[str], roadmap: str) -> list[str]:
    statuses = phase_statuses(roadmap)
    errors: list[str] = []
    for phase in sorted(phases):
        status = statuses.get(phase)
        if status is None:
            errors.append(f"Phase {phase} is not in {ROADMAP}.")
        elif not status.startswith(DONE_PREFIX):
            errors.append(
                f"Phase {phase} is implemented by this PR but its Status in {ROADMAP} is "
                f"{status!r}. Set it to '{DONE_PREFIX} ([#<pr>](<pr-url>))'."
            )
    return errors


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, encoding="utf-8").stdout


def main(base: str, head: str) -> int:
    paths = _git("diff", "--name-only", f"{base}...{head}").splitlines()
    phases: set[str] = set()
    for spec_dir in sorted(changed_spec_dirs(paths)):
        try:
            requirements = _git("show", f"{head}:specs/{spec_dir}/requirements.md")
        except subprocess.CalledProcessError:
            continue  # folder deleted or has no requirements.md
        if phase := phase_of(requirements):
            phases.add(phase)

    if not phases:
        print("This PR touches no phase spec folder; nothing to check.")
        return 0

    errors = problems(phases, _git("show", f"{head}:{ROADMAP}"))
    for error in errors:
        print(f"::error file={ROADMAP}::{error}")
    if not errors:
        print(f"Roadmap marks phase(s) {', '.join(sorted(phases))} as done.")
    return 1 if errors else 0


if __name__ == "__main__":
    # Windows consoles default to cp1252, which cannot print the status emoji.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
