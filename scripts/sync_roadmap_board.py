"""Mirror specs/roadmap.md on GitHub: labels, one milestone per roadmap milestone, one issue
per phase, and a Projects board holding the issues. Uses the `gh` CLI.

The roadmap stays the source of truth. Running this again updates what changed: issue titles,
bodies and milestones follow the roadmap, a phase marked "✅ Done" closes its issue and moves
its card to Done, a milestone whose phases are all done is closed. Cards a person moved to
"In Progress" stay there until the phase is done.

Usage:
  python scripts/sync_roadmap_board.py            apply
  python scripts/sync_roadmap_board.py --dry-run  print what would change, write nothing

Needs `gh auth login` with the `project` scope (`gh auth refresh -s project`).
"""

import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, cast

from check_roadmap import DONE_PREFIX, PHASE_ROW, ROADMAP
from setup_repo_rules import origin_repo

PROJECT_TITLE = "agentic-dev roadmap"
PHASE_LABEL = "roadmap-phase"
MARKER = re.compile(r"<!-- roadmap-phase: (\d+\.\d+) -->")
MILESTONE_HEADING = re.compile(r"^## Milestone (\d+): (.+?)\s*$")
PR_LINK = re.compile(r"\[#(\d+)\]")
TITLE_LIMIT = 100

# name -> (colour, description). Applied with --force, so colours and descriptions follow this.
LABELS: dict[str, tuple[str, str]] = {
    PHASE_LABEL: ("5319e7", "A phase of specs/roadmap.md (synced, edit the roadmap)"),
    "skip-roadmap": ("cfd3d7", "Planning-only PR: the roadmap check is skipped"),
    "type:feature": ("0e8a16", "New behaviour"),
    "type:fix": ("d73a4a", "Bug fix"),
    "type:plan": ("c5def5", "Spec or plan only, no implementation"),
    "type:chore": ("fef2c0", "Tooling, CI, dependencies, refactors"),
    "type:docs": ("0075ca", "Documentation only"),
    "area:engine": ("bfdadc", "packages/engine: spec, compiler, primitives"),
    "area:api": ("bfdadc", "FastAPI app, store, migrations"),
    "area:web": ("bfdadc", "Next.js app in web/"),
    "area:sandbox": ("bfdadc", "Sandbox containers and repo tools"),
    "area:ci": ("bfdadc", "GitHub Actions, scripts, repo rules"),
}


@dataclass
class Phase:
    number: str
    title: str
    done_when: str
    status: str

    @property
    def done(self) -> bool:
        return self.status.startswith(DONE_PREFIX)

    @property
    def pr(self) -> str | None:
        match = PR_LINK.search(self.status)
        return match.group(1) if match else None


@dataclass
class Milestone:
    number: int
    title: str
    description: str = ""
    phases: list[Phase] = field(default_factory=list[Phase])

    @property
    def name(self) -> str:
        return f"Milestone {self.number}: {self.title}"

    @property
    def done(self) -> bool:
        return bool(self.phases) and all(p.done for p in self.phases)


def parse_roadmap(roadmap: str) -> list[Milestone]:
    milestones: list[Milestone] = []
    current: Milestone | None = None
    for line in roadmap.splitlines():
        if match := MILESTONE_HEADING.match(line):
            current = Milestone(int(match.group(1)), match.group(2))
            milestones.append(current)
        elif line.startswith("## ") or line.startswith("---"):
            current = None
        elif current is None:
            continue
        elif PHASE_ROW.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            current.phases.append(Phase(cells[0], cells[1], cells[2], cells[-1]))
        elif line.strip() and not line.startswith("|") and not current.phases:
            current.description = f"{current.description} {line.strip()}".strip()
    return milestones


def issue_title(phase: Phase) -> str:
    title = f"{phase.number} {phase.title}"
    return title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1].rstrip() + "…"


def issue_body(phase: Phase, milestone: Milestone, repo: str) -> str:
    roadmap_url = f"https://github.com/{repo}/blob/main/{ROADMAP}"
    status = f"Done in #{phase.pr}" if phase.pr else ("Done" if phase.done else "Not started")
    return (
        f"<!-- roadmap-phase: {phase.number} -->\n"
        f"Phase **{phase.number}** of [{milestone.name}]({roadmap_url}).\n\n"
        f"### Scope\n\n{phase.title}\n\n"
        f"### Done when\n\n{phase.done_when}\n\n"
        f"**Status:** {status}\n\n"
        f"_Synced from `{ROADMAP}` by `scripts/sync_roadmap_board.py`: "
        "edit the roadmap, not this issue._\n"
    )


class GitHub:
    def __init__(self, repo: str, dry_run: bool) -> None:
        self.repo = repo
        self.owner = repo.split("/")[0]
        self.dry_run = dry_run

    def read(self, *args: str) -> Any:
        return self._run(args, payload=None)

    def write(self, summary: str, *args: str, payload: object = None, check: bool = True) -> Any:
        print(("would " if self.dry_run else "") + summary)
        if self.dry_run:
            return None
        return self._run(args, payload=payload, check=check)

    def _run(self, args: tuple[str, ...], payload: object, check: bool = True) -> Any:
        if payload is not None:
            args = (*args, "--input", "-")
        result = subprocess.run(
            ["gh", *args],
            input=None if payload is None else json.dumps(payload),
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            if not check:
                return None
            sys.exit(f"gh {' '.join(args)} failed:\n{result.stderr.strip()}")
        return json.loads(result.stdout) if result.stdout.strip() else None


def sync_labels(gh: GitHub) -> None:
    existing = cast(
        list[dict[str, str]],
        gh.read("label", "list", "--limit", "500", "--json", "name,color,description"),
    )
    by_name = {label["name"]: label for label in existing}
    wanted = dict(LABELS)
    for n in range(0, 11):
        wanted[f"milestone:{n}"] = ("1d76db", f"Roadmap milestone {n}")
    for name, (color, description) in wanted.items():
        have = by_name.get(name)
        if have and have["color"].lower() == color and have["description"] == description:
            continue
        gh.write(
            f"{'update' if have else 'create'} label {name}",
            "label",
            "create",
            name,
            "--color",
            color,
            "--description",
            description,
            "--force",
        )


def sync_milestones(gh: GitHub, milestones: list[Milestone]) -> dict[int, int]:
    """Return roadmap milestone number -> GitHub milestone number."""
    existing = cast(
        list[dict[str, Any]],
        gh.read("api", f"repos/{gh.repo}/milestones?state=all&per_page=100"),
    )
    by_title = {m["title"]: m for m in existing}
    numbers: dict[int, int] = {}
    for milestone in milestones:
        state = "closed" if milestone.done else "open"
        wanted = {"title": milestone.name, "description": milestone.description, "state": state}
        have = by_title.get(milestone.name)
        if have is None:
            created = gh.write(
                f"create milestone {milestone.name!r}",
                "api",
                "-X",
                "POST",
                f"repos/{gh.repo}/milestones",
                payload=wanted,
            )
            numbers[milestone.number] = cast(dict[str, int], created)["number"] if created else -1
            continue
        numbers[milestone.number] = have["number"]
        if (have["description"] or "") != milestone.description or have["state"] != state:
            gh.write(
                f"update milestone {milestone.name!r} ({state})",
                "api",
                "-X",
                "PATCH",
                f"repos/{gh.repo}/milestones/{have['number']}",
                payload=wanted,
            )
    return numbers


def sync_issues(
    gh: GitHub, milestones: list[Milestone], numbers: dict[int, int]
) -> dict[str, tuple[str, bool]]:
    """Return phase -> (issue URL, done)."""
    existing = cast(
        list[dict[str, Any]],
        gh.read(
            "issue",
            "list",
            "--label",
            PHASE_LABEL,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,title,body,state,milestone,labels,url",
        ),
    )
    by_phase: dict[str, dict[str, Any]] = {}
    for issue in existing:
        if match := MARKER.search(issue["body"] or ""):
            by_phase[match.group(1)] = issue

    urls: dict[str, tuple[str, bool]] = {}
    for milestone in milestones:
        labels = sorted({PHASE_LABEL, f"milestone:{milestone.number}"})
        for phase in milestone.phases:
            title, body = issue_title(phase), issue_body(phase, milestone, gh.repo)
            state = "closed" if phase.done else "open"
            payload: dict[str, object] = {
                "title": title,
                "body": body,
                "labels": labels,
                "milestone": numbers[milestone.number],
                "state": state,
            }
            if phase.done:
                payload["state_reason"] = "completed"
            have = by_phase.get(phase.number)
            if have is None:
                created = gh.write(
                    f"create issue {title!r} ({state})",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{gh.repo}/issues",
                    payload={**payload, "state": "open"},
                )
                if created and phase.done:
                    number = cast(dict[str, int], created)["number"]
                    gh.write(
                        f"close issue #{number}",
                        "api",
                        "-X",
                        "PATCH",
                        f"repos/{gh.repo}/issues/{number}",
                        payload=payload,
                    )
                url = (
                    cast(dict[str, str], created)["html_url"]
                    if created
                    else f"<new {phase.number}>"
                )
                urls[phase.number] = (url, phase.done)
                continue
            urls[phase.number] = (have["url"], phase.done)
            have_labels = sorted(label["name"] for label in have["labels"])
            have_milestone = cast(dict[str, int], have["milestone"] or {}).get("number")
            # Extra labels people add (type:, area:) are kept; only the synced ones are required.
            if (
                have["title"] == title
                and (have["body"] or "").strip() == body.strip()
                and set(labels) <= set(have_labels)
                and have_milestone == numbers[milestone.number]
                and have["state"].lower() == state
            ):
                continue
            payload["labels"] = sorted(set(labels) | set(have_labels))
            gh.write(
                f"update issue #{have['number']} {title!r} ({state})",
                "api",
                "-X",
                "PATCH",
                f"repos/{gh.repo}/issues/{have['number']}",
                payload=payload,
            )
    return urls


def sync_project(gh: GitHub, issues: dict[str, tuple[str, bool]]) -> None:
    projects = cast(
        dict[str, list[dict[str, Any]]],
        gh.read("project", "list", "--owner", gh.owner, "--format", "json", "--limit", "100"),
    )
    project = next((p for p in projects["projects"] if p["title"] == PROJECT_TITLE), None)
    if project is None:
        project = gh.write(
            f"create project {PROJECT_TITLE!r}",
            "project",
            "create",
            "--owner",
            gh.owner,
            "--title",
            PROJECT_TITLE,
            "--format",
            "json",
        )
        if project is None:  # dry run
            print(f"would add {len(issues)} issues to the project")
            return
        gh.write(
            "describe the project",
            "project",
            "edit",
            str(project["number"]),
            "--owner",
            gh.owner,
            "--description",
            f"Roadmap phases of {gh.repo}, synced from {ROADMAP}",
        )
    number = str(project["number"])
    # Already linked is an error from gh; either way the project shows on the repo.
    gh.write(
        f"link project to {gh.repo}",
        "project",
        "link",
        number,
        "--owner",
        gh.owner,
        "--repo",
        gh.repo,
        check=False,
    )

    fields = cast(
        dict[str, list[dict[str, Any]]],
        gh.read("project", "field-list", number, "--owner", gh.owner, "--format", "json"),
    )
    status = next(f for f in fields["fields"] if f["name"] == "Status")
    options = {o["name"]: o["id"] for o in status["options"]}

    items = cast(
        dict[str, list[dict[str, Any]]],
        gh.read(
            "project",
            "item-list",
            number,
            "--owner",
            gh.owner,
            "--format",
            "json",
            "--limit",
            "1000",
        ),
    )
    by_url = {item["content"].get("url"): item for item in items["items"] if item.get("content")}

    for phase, (url, done) in issues.items():
        item = by_url.get(url)
        current = item.get("status") if item else None
        if item is None:
            added = gh.write(
                f"add phase {phase} to the project",
                "project",
                "item-add",
                number,
                "--owner",
                gh.owner,
                "--url",
                url,
                "--format",
                "json",
            )
            item_id = cast(dict[str, str], added)["id"] if added else None
        else:
            item_id = item["id"]
        wanted = "Done" if done else ("Todo" if current in (None, "Done") else current)
        if wanted == current:
            continue
        gh.write(
            f"set phase {phase} to {wanted}",
            "project",
            "item-edit",
            "--id",
            str(item_id),
            "--project-id",
            project["id"],
            "--field-id",
            status["id"],
            "--single-select-option-id",
            options[wanted],
        )
    print(f"Project: {project.get('url', PROJECT_TITLE)}")


def main(dry_run: bool) -> int:
    with open(ROADMAP, encoding="utf-8") as f:
        milestones = parse_roadmap(f.read())
    gh = GitHub(origin_repo(), dry_run)
    sync_labels(gh)
    numbers = sync_milestones(gh, milestones)
    issues = sync_issues(gh, milestones, numbers)
    sync_project(gh, issues)
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    args = sys.argv[1:]
    if args not in ([], ["--dry-run"]):
        sys.exit(__doc__)
    sys.exit(main(dry_run=args == ["--dry-run"]))
