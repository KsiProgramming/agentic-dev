"""What a gate with `review` does with the review's findings (13.6): split them by `block_at`,
map them onto the writers' diffs, and turn them into the comments that send the work back or that
the approver reads on the lines they name.

Everything here is model output (findings): data, never instructions, and shown as text.
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from agentic_engine.gate import GateComment
from agentic_runtime.findings import (
    SEVERITIES,
    Category,
    Finding,
    FindingsReport,
    Severity,
    merge_key,
)

MAX_REVIEW_COMMENTS = 100
"""The most review comments a gate shows."""

MAX_SEND_BACK = 19
"""The most findings one send-back lists (a request for changes carries 20 comments; the last is
the count of those left out)."""

REVIEW_ITEM = "Review"
"""The heading the writer's next input has the findings under (`## Review`)."""

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_DIFF_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def severity_rank(severity: Severity) -> int:
    """0 for the most severe."""
    return SEVERITIES.index(severity)


def changed_lines(diff: str) -> dict[str, list[tuple[int, int]]]:
    """The new-side line ranges `diff` (the text `repo.diff` returns) adds or changes, by path.
    A file whose diff has no hunk (a rename, a binary) is in the result with no ranges."""
    found: dict[str, list[tuple[int, int]]] = {}
    path: str | None = None
    for line in diff.splitlines():
        if (file := _DIFF_FILE.match(line)) is not None:
            path = str(file.group(2) or file.group(1))
            found.setdefault(path, [])
        elif path is not None and (hunk := _HUNK.match(line)) is not None:
            start = int(hunk.group(1))
            count = int(hunk.group(2)) if hunk.group(2) is not None else 1
            found[path].append((start, start + max(count, 1) - 1))
    return found


class ReviewComment(BaseModel):
    """One finding of the review, as the gate shows it: where it is, which writer's diff holds the
    file, whether the line is in a changed hunk, and whether it blocks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fingerprint: str
    severity: Severity
    category: Category
    lenses: list[str]
    path: str
    line: int | None = None
    end_line: int | None = None
    message: str
    node_id: str | None = Field(default=None, description="The writer whose diff holds the file.")
    in_diff: bool = False
    blocking: bool = False


class ReviewShown(BaseModel):
    """What a gate with `review` shows (`gate_waiting`'s `review`)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    from_: str = Field(alias="from")
    version: int
    block_at: Severity
    rounds_left: int
    comments: list[ReviewComment]
    failed_lenses: list[str]
    counts: dict[Severity, int]
    truncated: bool = False


class ReviewInput(BaseModel):
    """What a gate with `review` is given by the step before it (as the checkpoint holds it): what
    to show, and the comments that send the work back when it does (`send`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shown: ReviewShown
    send: list[GateComment] = Field(default_factory=list[GateComment])


def lenses_of(finding: Finding) -> list[str]:
    """The lenses that reported `finding`: the merged report's sources, else its tool."""
    names = finding.sources or [finding.tool]
    return [n.removeprefix("review_") for n in names]


def failed_lenses(report: FindingsReport) -> list[str]:
    """The review agents that could not run, from the merged report's failed branch checks."""
    return [
        (c.tool or c.path).removeprefix("review_")
        for c in report.checks
        if c.kind == "branch" and c.status == "failed"
    ]


def comments_of(
    report: FindingsReport, block_at: Severity, diffs: Mapping[str, str]
) -> list[ReviewComment]:
    """Every finding of `report` as a comment (at most `MAX_REVIEW_COMMENTS`, most severe first).
    `diffs` is each writer's `repo.diff` text, in run order: a file belongs to the latest writer
    whose diff holds it, and its line is `in_diff` when a hunk of that diff covers it."""
    changed = {writer: changed_lines(text) for writer, text in diffs.items()}
    comments: list[ReviewComment] = []
    for f in report.findings[:MAX_REVIEW_COMMENTS]:
        owner = next((w for w in reversed(list(changed)) if f.path in changed[w]), None)
        in_diff = False
        if owner is not None:
            ranges = changed[owner][f.path]
            in_diff = f.line is None or not ranges or any(a <= f.line <= b for a, b in ranges)
        comments.append(
            ReviewComment(
                fingerprint=f.fingerprint or merge_key(f),
                severity=f.severity,
                category=f.category,
                lenses=lenses_of(f),
                path=f.path,
                line=f.line,
                end_line=f.end_line,
                message=f.message,
                node_id=owner,
                in_diff=in_diff,
                blocking=severity_rank(f.severity) <= severity_rank(block_at),
            )
        )
    return comments


def shown_of(
    name: str,
    version: int,
    report: FindingsReport,
    block_at: Severity,
    rounds_left: int,
    diffs: Mapping[str, str],
) -> ReviewShown:
    """What the gate shows for the report `name` at `version`."""
    counts = Counter(f.severity for f in report.findings)
    return ReviewShown.model_validate(
        {
            "from": name,
            "version": version,
            "block_at": block_at,
            "rounds_left": rounds_left,
            "comments": comments_of(report, block_at, diffs),
            "failed_lenses": failed_lenses(report),
            "counts": {s: counts.get(s, 0) for s in SEVERITIES},
            "truncated": report.truncated or len(report.findings) > MAX_REVIEW_COMMENTS,
        }
    )


def where(comment: ReviewComment) -> str:
    """`path:line` (or `path:line-end_line`, or just the path)."""
    if comment.line is None:
        return comment.path
    end = f"-{comment.end_line}" if comment.end_line and comment.end_line != comment.line else ""
    return f"{comment.path}:{comment.line}{end}"


def send_back_comments(shown: ReviewShown) -> list[GateComment]:
    """The blocking findings as the comments that send the work back: one line each under
    `## Review` (severity, `path:line`, lenses, message), most severe first, at most
    `MAX_SEND_BACK` and a last one counting the rest. Data for the writer, never instructions."""
    blocking = [c for c in shown.comments if c.blocking]
    comments = [
        GateComment(
            item=REVIEW_ITEM,
            text=f"{c.severity} {where(c)} [{', '.join(c.lenses)}]: {c.message}"[:3900],
        )
        for c in blocking[:MAX_SEND_BACK]
    ]
    if len(blocking) > MAX_SEND_BACK:
        left = len(blocking) - MAX_SEND_BACK
        comments.append(
            GateComment(
                item=REVIEW_ITEM, text=f"...and {left} more blocking finding(s) not listed."
            )
        )
    return comments


MAX_NOTES_CHARS = 8_000
"""The most characters of review notes a pull request body gets."""

_TAG = re.compile(r"<[^>]*>")
_MENTION = re.compile(r"@(?=[A-Za-z0-9_])")


def neutralise_notes(text: str) -> str:
    """Review notes as they go into a pull request body (13.6): HTML tags removed, every `@name`
    mention given a zero-width joiner after the `@` so it notifies nobody, and the whole capped at
    `MAX_NOTES_CHARS` with a note. The notes are model output: never trusted."""
    clean = _MENTION.sub("@\u200d", _TAG.sub("", text))
    if len(clean) > MAX_NOTES_CHARS:
        clean = clean[:MAX_NOTES_CHARS].rstrip() + "\n\n(cut here: the run's review has the rest)"
    return clean


def notes_text(comments: Sequence[ReviewComment]) -> str:
    """The comments left after the approval, as the Markdown a pull request body gets: one bullet
    each (severity, `path:line`, lenses, message). The engine neutralises mentions and strips
    HTML where it publishes it."""
    if not comments:
        return "No review comments."
    return "\n".join(
        f"- **{c.severity}** `{where(c)}` ({', '.join(c.lenses)}): {c.message}" for c in comments
    )
