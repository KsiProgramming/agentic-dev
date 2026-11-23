"""One matcher for protected paths (13.5), used by the repo tools and the workflow validator.

Paths are repo-relative and normalised (`normalise`); globs support `**` (any depth, also none
when it is a whole segment), `*` (within one segment) and `?` (one character of a segment).
Matching ignores case: a checkout on Windows or macOS treats case variants as one file, so
refusing more is the safe side."""

import re
from functools import lru_cache
from pathlib import PurePosixPath

_DRIVE = re.compile(r"^[A-Za-z]:")

ANALYZER_CONFIG_GLOBS: tuple[str, ...] = (
    "**/.editorconfig",
    "**/.globalconfig",
    "**/*.globalconfig",
    "**/*.ruleset",
    "**/Directory.Build.props",
    "**/Directory.Build.targets",
    "**/ruff.toml",
    "**/.ruff.toml",
    "**/biome.json",
    "**/biome.jsonc",
    "**/.shellcheckrc",
    "**/.gitleaks.toml",
    "**/.gitleaksignore",
)
"""The analyzer and scanner config files no writer may change (13.5), at any depth: the platform's
protected defaults and what the evidence step reads from the run's base (`scan.lint config:
"base"`). The engine lists why each is protected (`agentic_engine.protect`)."""
_UNSUPPORTED = "[]{}!"


def normalise(path: str) -> str | None:
    """`path` relative to the repo root with `/` separators and no `.` segments (`.` for the
    root), or None if it is absolute or leaves the repo."""
    path = path.replace("\\", "/").strip()
    if path.startswith("/") or _DRIVE.match(path):
        return None
    parts = [p for p in PurePosixPath(path).parts if p != "."]
    if ".." in parts:
        return None
    return "/".join(parts) or "."


def glob_problem(glob: str) -> str | None:
    """Why `glob` cannot be a protected path pattern, or None if it can."""
    if not glob.strip():
        return "is empty"
    text = glob.replace("\\", "/").strip()
    if text.startswith("/") or _DRIVE.match(text):
        return "is absolute; write it relative to the repo root"
    if ".." in text.split("/"):
        return "leaves the repo (`..`)"
    if bad := [c for c in _UNSUPPORTED if c in text]:
        return f"uses {bad[0]!r}, which is not supported; use `**`, `*` and `?`"
    if text.strip("/.") == "":
        return "matches nothing in particular; name a path or a pattern"
    return None


@lru_cache(maxsize=512)
def _compile(glob: str) -> re.Pattern[str]:
    text = "/".join(p for p in glob.replace("\\", "/").strip().split("/") if p not in ("", "."))
    parts = text.split("/")
    out: list[str] = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
            continue
        out.append(
            "".join(
                "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
                for c in re.sub(r"\*+", "*", part)
            )
        )
        if not last:
            out.append("/")
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


def matches(glob: str, path: str) -> bool:
    """Whether the repo path `path` (normalised here) matches `glob`. A path that leaves the
    repo matches nothing."""
    relative = normalise(path)
    if relative is None:
        return False
    return _compile(glob).fullmatch(relative) is not None


def first_match(globs: list[str] | tuple[str, ...], path: str) -> str | None:
    """The first of `globs` that matches `path`, or None."""
    return next((g for g in globs if matches(g, path)), None)
