"""Keeping repo tools inside the repo: path arguments are normalised relative to the repo root,
and every shell script starts with `CONFINE`, which resolves symlinks and refuses anything outside
the root."""

import re
from pathlib import PurePosixPath

_DRIVE = re.compile(r"^[A-Za-z]:")

# Shell prelude: `cd -P` (or, for a file, `cd -P` to its directory) resolves symlinks, then the
# resolved directory must sit under the repo root. Exit 3: no such path; exit 4: outside the repo.
# `$1` is the repo-relative path. On success `$target` names the path from the new directory.
CONFINE = """
root=$(pwd -P)
if [ -d "$1" ]; then
  cd -P -- "$1" 2>/dev/null || exit 3
  target=.
elif [ -e "$1" ]; then
  cd -P -- "$(dirname -- "$1")" 2>/dev/null || exit 3
  target=$(basename -- "$1")
  if [ -L "$target" ]; then
    case "$(readlink -f -- "$target")" in "$root"/*) ;; *) exit 4 ;; esac
  fi
else
  exit 3
fi
case "$(pwd -P)/" in "$root"/*) ;; *) exit 4 ;; esac
"""
NOT_FOUND = 3
OUTSIDE = 4


def repo_relative(path: str) -> str | None:
    """`path` normalised relative to the repo root (`.` for the root), or None if it is absolute
    or leaves the repo."""
    path = path.replace("\\", "/").strip()
    if path.startswith("/") or _DRIVE.match(path):
        return None
    parts = [p for p in PurePosixPath(path).parts if p != "."]
    if ".." in parts:
        return None
    return "/".join(parts) or "."
