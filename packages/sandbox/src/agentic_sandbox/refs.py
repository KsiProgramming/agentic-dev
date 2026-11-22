"""Reading a writer's branch from git, without a worktree (13.1).

`branch_diff` is what a branch changed on top of the clone's `HEAD`, as a file list and a unified
diff. `show_file`, `list_tree` and `grep_tree` read the branch as last committed, through git refs
(`git cat-file`, `ls-tree`, `grep`), so they work after a restore (12.2) when no worktree exists,
see only committed work, and cannot write. Paths are repo-relative and never leave the tree: git
resolves them inside the commit, so a symlink is a blob holding its target, not a way out.

Repo content is data: git runs with `GIT_SAFETY` and `safe.directory` for the checkout, and nothing
read here is executed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agentic_sandbox.bundle import BRANCH_PATTERN
from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import ExecResult, Sandbox
from agentic_sandbox.review import BranchNotFoundError, FileStatus, parse_name_status
from agentic_sandbox.worktree import GIT_SAFETY

_NO_BRANCH = 8
_NOT_FOUND = 3
_NOT_A_FILE = 5
_BINARY = 6

# The prelude of every script: `$1` the branch, `$2` the checkout (trusted by git although root
# owns it). Exits 8 when the branch does not exist.
_PRELUDE = f"""
branch=$1
checkout=$2
shift 2
g() {{ git -c safe.directory="$checkout" --literal-pathspecs {" ".join(GIT_SAFETY)} "$@"; }}
g rev-parse --verify -q "refs/heads/$branch" >/dev/null || exit {_NO_BRANCH}
ref="refs/heads/$branch"
"""

# `$3` is `status`, `numstat` or `diff`, `$4` the pathspec (or empty), `$5` the byte cap.
_DIFF_SCRIPT = (
    _PRELUDE
    + """
mode=$1
spec=$2
cap=$3
base=$(g rev-parse --verify -q 'HEAD^{commit}') || exit 1
set -- "$base" "$ref"
if [ -n "$spec" ]; then set -- "$@" -- "$spec"; fi
case "$mode" in
  status)
    printf '%s\\0' "$base"
    g -c core.quotePath=false diff --name-status -z -M --no-ext-diff "$@" ;;
  numstat) g -c core.quotePath=false diff --numstat -z -M --no-ext-diff "$@" ;;
  diff) g -c core.quotePath=false diff -M --no-ext-diff --no-color "$@" | head -c "$cap" ;;
esac
"""
)

# Prints the number of commits the branch holds on top of the clone's `HEAD`.
_AHEAD_SCRIPT = (
    _PRELUDE
    + """
g rev-list --count "HEAD..$ref"
"""
)

# `$3` the path, `$4` the first line, `$5` one past the last, `$6` the byte cap. Prints the file's
# line count, then the lines asked for.
_SHOW_SCRIPT = (
    _PRELUDE
    + """
path=$1
object="$ref:$path"
case "$(g cat-file -t "$object" 2>/dev/null)" in
  blob) ;;
  tree) exit 5 ;;
  *) exit 3 ;;
esac
bytes=$(g cat-file blob "$object" | head -c 8192 | wc -c)
nuls=$(g cat-file blob "$object" | head -c 8192 | tr -d '\\000' | wc -c)
[ "$bytes" -eq "$nuls" ] || exit 6
g cat-file blob "$object" | wc -l
g cat-file blob "$object" | sed -n "$2,$3p" | head -c "$4"
"""
)

# `$3` the path (`.` for the root). Prints `<type> <path>` for every entry under it, NUL separated.
_TREE_SCRIPT = (
    _PRELUDE
    + """
path=$1
if [ "$path" = . ]; then object="$ref^{tree}"; else object="$ref:$path"; fi
[ "$(g cat-file -t "$object" 2>/dev/null)" = tree ] || exit 3
g -c core.quotePath=false ls-tree -r -t -z "$object"
"""
)

# `$3` the pattern (an extended regex), `$4` `-i` or empty, `$5` the path (`.` for all), `$6` the
# line cap. Prints `<ref>:<path>:<line>:<text>`; binary files are skipped.
_GREP_SCRIPT = (
    _PRELUDE
    + """
pattern=$1
case_flag=$2
path=$3
cap=$4
set -- -n -I -E
[ -z "$case_flag" ] || set -- "$@" -i
set -- "$@" -e "$pattern" "$ref"
if [ "$path" != . ]; then set -- "$@" -- "$path"; fi
g -c core.quotePath=false grep "$@" | head -n "$cap"
true
"""
)


@dataclass(frozen=True)
class DiffFile:
    """A file a branch changed, with the lines it added and removed (`None` for a binary file)."""

    path: str
    status: FileStatus
    old_path: str | None = None
    added: int | None = None
    removed: int | None = None

    @property
    def binary(self) -> bool:
        return self.added is None


@dataclass(frozen=True)
class BranchDiff:
    base_sha: str
    branch: str
    files: list[DiffFile]
    diff: str
    truncated: bool


@dataclass(frozen=True)
class FileSlice:
    """Lines of a file read at a branch: `text` is the lines asked for (cut at the byte cap),
    `total` the file's line count."""

    total: int
    text: str


class RefPathError(SandboxError):
    """A path read at a branch is not there (`missing`), is a directory (`not_a_file`) or is
    binary (`binary`)."""

    def __init__(self, kind: Literal["missing", "not_a_file", "binary"], path: str) -> None:
        super().__init__(f"{kind}: {path}")
        self.kind = kind
        self.path = path


# `$3` is the destination directory (created, empty), `$4` is `branch` or `base` (the clone's
# `HEAD`), the rest are paths to extract (none: the whole tree). Extracts the tree as last
# committed. `git archive` writes tar from git's own objects: nothing in the tree is executed, no
# hook or filter runs (`--worktree-attributes` is never given), and a symlink stays a symlink.
_ARCHIVE_SCRIPT = (
    _PRELUDE
    + """
dest=$1
which=$2
shift 2
mkdir -p -- "$dest" || exit 1
tree=$ref
[ "$which" = base ] && tree=HEAD
if [ $# -gt 0 ]; then
  g archive --format=tar "$tree" -- "$@" | tar -C "$dest" -xf - || exit 1
else
  g archive --format=tar "$tree" | tar -C "$dest" -xf - || exit 1
fi
"""
)

# `$3` is the byte cap. Prints the unified diff with no context from the clone's `HEAD` to the
# branch: only the hunks' positions are read from it.
_PATCH_SCRIPT = (
    _PRELUDE
    + """
cap=$1
base=$(g rev-parse --verify -q 'HEAD^{commit}') || exit 1
g -c core.quotePath=false diff -U0 -M --no-ext-diff --no-color --no-textconv \
  "$base" "$ref" | head -c "$cap"
"""
)


async def archive(
    sandbox: Sandbox, branch: str, dest: str, *, base: bool = False, paths: Sequence[str] = ()
) -> None:
    """Extract `branch`'s tree as last committed into the directory `dest` (created if it is
    missing), which must be under the staging directory (a job's work copy lives there, never in
    the checkout or a worktree). With `base`, the clone's `HEAD`, the commit the run started from,
    is extracted instead (`branch` must still exist); with `paths`, only those files. Like the
    reads above it works after a restore. Raises `BranchNotFoundError` if the branch does not
    exist, `ValueError` for a `dest` outside the staging directory, and `SandboxError` if the tree
    cannot be extracted."""
    _check_branch(branch)
    staging = sandbox.staging_dir.rstrip("/")
    if not dest.startswith(f"{staging}/") or ".." in dest.split("/"):
        raise ValueError(f"not a directory under the staging directory: {dest!r}")
    result = await _run(
        sandbox, _ARCHIVE_SCRIPT, branch, dest, "base" if base else "branch", *paths
    )
    _raise_if_missing(result.exit_code, branch)
    if result.exit_code != 0:
        raise SandboxError(f"could not extract branch {branch}")


async def branch_patch(sandbox: Sandbox, branch: str, *, max_bytes: int = 4 * 1024 * 1024) -> str:
    """What `branch` changed on top of the clone's `HEAD` as a unified diff with no context, cut at
    `max_bytes`. Raises `BranchNotFoundError` if the branch does not exist."""
    _check_branch(branch)
    result = await _run(sandbox, _PATCH_SCRIPT, branch, str(max_bytes))
    _raise_if_missing(result.exit_code, branch)
    if result.exit_code != 0:
        raise SandboxError(f"could not read the changes of branch {branch}")
    return result.stdout


async def branch_has_commits(sandbox: Sandbox, branch: str) -> bool:
    """Whether `branch` holds a commit on top of the clone's `HEAD`. A missing branch has none."""
    _check_branch(branch)
    result = await _run(sandbox, _AHEAD_SCRIPT, branch)
    if result.exit_code == _NO_BRANCH:
        return False
    if result.exit_code != 0 or not result.stdout.strip().isdigit():
        raise SandboxError(f"could not read branch {branch}")
    return int(result.stdout.strip()) > 0


async def branch_diff(
    sandbox: Sandbox, branch: str, *, path: str | None = None, max_bytes: int = 256 * 1024
) -> BranchDiff:
    """What `branch` changed on top of the clone's `HEAD`: each file with its status and its added
    and removed lines (a binary file is named, with no counts), and the unified diff with renames
    found, cut at `max_bytes` (`truncated`). `path` limits it to one file or directory. Raises
    `BranchNotFoundError` if the branch does not exist."""
    _check_branch(branch)
    spec = path or ""
    status = await _run(sandbox, _DIFF_SCRIPT, branch, "status", spec, str(max_bytes))
    _raise_if_missing(status.exit_code, branch)
    if status.exit_code != 0 or status.truncated:
        raise SandboxError(f"could not list the changes of branch {branch}")
    base, *fields = status.stdout.split("\0")
    changed = parse_name_status([f for f in fields if f != ""])

    numstat = await _run(sandbox, _DIFF_SCRIPT, branch, "numstat", spec, str(max_bytes))
    if numstat.exit_code != 0 or numstat.truncated:
        raise SandboxError(f"could not count the changes of branch {branch}")
    counts = _parse_numstat(numstat.stdout)
    files = [
        DiffFile(
            path=f.path,
            status=f.status,
            old_path=f.old_path,
            added=counts.get(f.path, (None, None))[0],
            removed=counts.get(f.path, (None, None))[1],
        )
        for f in changed
    ]

    # One byte more than the cap, to tell whether anything was cut.
    text = await _run(sandbox, _DIFF_SCRIPT, branch, "diff", spec, str(max_bytes + 1))
    if text.exit_code != 0:
        raise SandboxError(f"could not read the diff of branch {branch}")
    raw = text.stdout.encode()
    truncated = len(raw) > max_bytes
    diff = raw[:max_bytes].decode(errors="replace")
    if truncated and "\n" in diff:
        diff = diff[: diff.rindex("\n") + 1]  # not a partial line
    return BranchDiff(base_sha=base, branch=branch, files=files, diff=diff, truncated=truncated)


async def show_file(
    sandbox: Sandbox, branch: str, path: str, *, first: int, last: int, max_bytes: int
) -> FileSlice:
    """Lines `first` to `last` of `path` as `branch` last committed it, cut to `max_bytes`, with
    the file's line count. Raises `BranchNotFoundError`, or `RefPathError` for a path that is
    missing, a directory or binary."""
    _check_branch(branch)
    result = await _run(sandbox, _SHOW_SCRIPT, branch, path, str(first), str(last), str(max_bytes))
    _raise_if_missing(result.exit_code, branch)
    _raise_if_path(result.exit_code, path)
    count, _, body = result.stdout.partition("\n")
    if result.exit_code != 0 or not count.strip().isdigit():
        raise SandboxError(f"could not read {path}")
    return FileSlice(total=int(count), text=body)


async def list_tree(sandbox: Sandbox, branch: str, path: str, *, depth: int) -> list[str]:
    """The entries under `path` as `branch` last committed them, to `depth` levels, as paths
    relative to the repo root; directories end with `/`. Sorted. Raises `BranchNotFoundError`, or
    `RefPathError` (`missing`) if `path` is not a directory there."""
    _check_branch(branch)
    result = await _run(sandbox, _TREE_SCRIPT, branch, path)
    _raise_if_missing(result.exit_code, branch)
    if result.exit_code == _NOT_FOUND:
        raise RefPathError("missing", path)
    if result.exit_code != 0:
        raise SandboxError("could not list the files")
    prefix = "" if path == "." else f"{path}/"
    entries: list[str] = []
    for item in result.stdout.split("\0"):
        meta, _, name = item.partition("\t")
        if not name or name.count("/") >= depth:
            continue
        entries.append(
            f"{prefix}{name}/" if meta.split(" ")[1:2] == ["tree"] else f"{prefix}{name}"
        )
    return sorted(entries)


async def grep_tree(
    sandbox: Sandbox,
    branch: str,
    pattern: str,
    *,
    path: str = ".",
    ignore_case: bool = False,
    max_lines: int,
) -> list[tuple[str, int, str]]:
    """The lines of `branch`'s text files that match the extended regex `pattern`, as
    `(path, line, text)` by path then line; at most `max_lines` are read. Binary files are
    skipped. Raises `BranchNotFoundError`."""
    _check_branch(branch)
    result = await _run(
        sandbox, _GREP_SCRIPT, branch, pattern, "-i" if ignore_case else "", path, str(max_lines)
    )
    _raise_if_missing(result.exit_code, branch)
    if result.exit_code != 0:
        raise SandboxError("could not search the files")
    prefix = f"refs/heads/{branch}:"
    hits: list[tuple[str, int, str]] = []
    for line in result.stdout.splitlines():
        if not line.startswith(prefix):
            continue
        file, _, rest = line[len(prefix) :].partition(":")
        number, _, text = rest.partition(":")
        if number.isdigit():
            hits.append((file, int(number), text))
    return sorted(hits, key=lambda h: (h[0], h[1]))


def _check_branch(branch: str) -> None:
    if not BRANCH_PATTERN.match(branch) or ".." in branch:
        raise ValueError(f"not a branch name: {branch!r}")


async def _run(sandbox: Sandbox, script: str, branch: str, *args: str) -> ExecResult:
    return await sandbox.exec(
        ["sh", "-c", script, "refs", branch, sandbox.workdir, *args], timeout_s=60.0
    )


def _raise_if_missing(exit_code: int, branch: str) -> None:
    if exit_code == _NO_BRANCH:
        raise BranchNotFoundError(f"branch {branch} does not exist")


def _raise_if_path(exit_code: int, path: str) -> None:
    if exit_code == _NOT_FOUND:
        raise RefPathError("missing", path)
    if exit_code == _NOT_A_FILE:
        raise RefPathError("not_a_file", path)
    if exit_code == _BINARY:
        raise RefPathError("binary", path)


def _parse_numstat(text: str) -> dict[str, tuple[int | None, int | None]]:
    """`git diff --numstat -z`: `added<TAB>removed<TAB>path<NUL>`, or for a rename
    `added<TAB>removed<TAB><NUL>old<NUL>new<NUL>`. A binary file counts `-`."""
    tokens = text.split("\0")
    counts: dict[str, tuple[int | None, int | None]] = {}
    i = 0
    while i < len(tokens) and tokens[i]:
        added, removed, name = tokens[i].split("\t", 2)
        if name == "" and i + 2 < len(tokens):
            name = tokens[i + 2]
            i += 3
        else:
            i += 1
        counts[name] = (
            int(added) if added.isdigit() else None,
            int(removed) if removed.isdigit() else None,
        )
    return counts
