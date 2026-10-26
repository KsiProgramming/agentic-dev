"""A writer's branch as a gate shows it, and the approver's edits committed onto it.

`branch_changes` lists what the branch changed on top of the clone's `HEAD` (its base, as for
`export_branch`), with each side's size; `read_blobs` reads file contents from git in one go, as
bytes, through a staged file (exec output is text, cut at `MAX_OUTPUT_BYTES`). `commit_files`
writes files into the writer's worktree with the same confinement as the `repo` tool's writes and
commits only them.

Repo content is data: git runs with `GIT_SAFETY`, and nothing read here is executed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from agentic_sandbox.bundle import BRANCH_PATTERN
from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import Sandbox
from agentic_sandbox.worktree import (
    AGENT_IDENTITY,
    GIT_SAFETY,
    WRITE_FILE_SCRIPT,
    WRITE_OUTSIDE,
    Worktree,
)

type FileStatus = Literal["added", "modified", "deleted", "renamed"]

_NO_BRANCH = 8
_STATUS: dict[str, FileStatus] = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed"}

# `$1` the branch, `$2` the checkout (trusted by git although root owns it). Prints the base
# commit and a NUL, then the branch's changes on top of it (`--name-status -z`, renames found).
_CHANGES_SCRIPT = f"""
checkout=$2
g() {{ git -c safe.directory="$checkout" {" ".join(GIT_SAFETY)} "$@"; }}
base=$(g rev-parse --verify -q 'HEAD^{{commit}}') || exit 1
g rev-parse --verify -q "refs/heads/$1" >/dev/null || exit {_NO_BRANCH}
printf '%s\\0' "$base"
g -c core.quotePath=false diff --name-status -z -M --no-ext-diff "$base" "refs/heads/$1"
"""

# `$1` the checkout, `$2` the file to write, then one `<rev>:<path>` per argument: writes
# `git cat-file --batch` output for them to the file. With `--sizes`, prints
# `--batch-check` output instead.
_BLOBS_SCRIPT = f"""
checkout=$1
out=$2
shift 2
g() {{ git -c safe.directory="$checkout" {" ".join(GIT_SAFETY)} "$@"; }}
if [ "$out" = --sizes ]; then
  printf '%s\\n' "$@" | g cat-file --batch-check='%(objecttype) %(objectsize)'
else
  printf '%s\\n' "$@" | g cat-file --batch > "$out"
fi
"""

# `$1` the message, `$2` and `$3` the identity, then the paths: stages and commits only them,
# then prints the branch tip. Prints the tip without committing if they did not change.
_COMMIT_SCRIPT = f"""
msg=$1
name=$2
email=$3
shift 3
g() {{ git {" ".join(GIT_SAFETY)} "$@"; }}
g add -- "$@" || exit 1
if ! g diff --cached --quiet -- "$@"; then
  g -c user.name="$name" -c user.email="$email" commit -q --no-verify -m "$msg" --only -- "$@" \\
    || exit 1
fi
g rev-parse HEAD
"""


class BranchNotFoundError(SandboxError):
    """The branch does not exist: its writer has not written yet."""


@dataclass(frozen=True)
class ChangedFile:
    """A file a branch changed. A side's size is `None` where the file does not exist."""

    path: str
    status: FileStatus
    old_path: str | None = None
    before_size: int | None = None
    after_size: int | None = None


@dataclass(frozen=True)
class BranchChanges:
    base_sha: str
    branch: str
    files: list[ChangedFile]


async def branch_changes(sandbox: Sandbox, branch: str) -> BranchChanges:
    """The files `branch` changed on top of the clone's `HEAD`, with their sizes. `sandbox` is
    the run's sandbox, not a worktree. Raises `BranchNotFoundError` if the branch does not exist,
    and `SandboxError` if git fails."""
    if not BRANCH_PATTERN.match(branch) or ".." in branch:
        raise ValueError(f"not a branch name: {branch!r}")
    result = await sandbox.exec(
        ["sh", "-c", _CHANGES_SCRIPT, "branch_changes", branch, sandbox.workdir], timeout_s=60.0
    )
    if result.exit_code == _NO_BRANCH:
        raise BranchNotFoundError(f"branch {branch} does not exist")
    if result.exit_code != 0 or result.truncated:
        raise SandboxError(f"could not list the changes of branch {branch}")
    base, *fields = result.stdout.split("\0")
    files = _parse_name_status([f for f in fields if f != ""] if fields else [])
    sizes = await _sizes(sandbox, base, branch, files)
    return BranchChanges(base_sha=base, branch=branch, files=sizes)


async def read_blobs(sandbox: Sandbox, specs: Sequence[str]) -> list[bytes | None]:
    """The contents of each `<rev>:<path>` in `specs`, `None` for one that is missing or not a
    file. Raises `SandboxError` if git fails or the contents are too large to hand out."""
    if not specs:
        return []
    _refuse_newlines(specs)
    out = f"{sandbox.staging_dir}/{uuid4().hex}.blobs"
    result = await sandbox.exec(
        ["sh", "-c", _BLOBS_SCRIPT, "read_blobs", sandbox.workdir, out, *specs], timeout_s=60.0
    )
    if result.exit_code != 0:
        raise SandboxError("could not read the branch's files")
    return _parse_batch(await sandbox.take_file(out), len(specs))


async def commit_files(tree: Worktree, files: Sequence[tuple[str, bytes]], message: str) -> str:
    """Write each `(path, data)` into `tree` (paths relative to it) and commit only those files
    on its branch, as the agent identity; return the branch tip. Files that already hold `data`
    make no commit. Raises `SandboxError` if a path leaves the worktree or git fails."""
    paths: list[str] = []
    for path, data in files:
        staged = await tree.put_file(data)
        result = await tree.exec(
            ["sh", "-c", WRITE_FILE_SCRIPT, "commit_files", f"./{path}", staged]
        )
        if result.exit_code == WRITE_OUTSIDE:
            raise SandboxError(f"{path} is outside the worktree")
        if result.exit_code != 0:
            raise SandboxError(f"could not write {path}")
        paths.append(f"./{path}")
    name, email = AGENT_IDENTITY
    result = await tree.exec(
        ["sh", "-c", _COMMIT_SCRIPT, "commit_files", message, name, email, *paths], timeout_s=60.0
    )
    tip = result.stdout.strip()
    if result.exit_code != 0 or len(tip) != 40:
        raise SandboxError(f"could not commit on {tree.branch}")
    return tip


def _parse_name_status(fields: list[str]) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    i = 0
    while i < len(fields):
        code = fields[i][:1]
        if code in ("R", "C"):
            old, new = fields[i + 1], fields[i + 2]
            # A copy leaves the old file as it was: to the approver, the new one is added.
            if code == "R":
                files.append(ChangedFile(path=new, status="renamed", old_path=old))
            else:
                files.append(ChangedFile(path=new, status="added"))
            i += 3
        else:
            # `T` (a type change, e.g. a file turned symlink) reads as a modification.
            files.append(ChangedFile(path=fields[i + 1], status=_STATUS.get(code, "modified")))
            i += 2
    return files


async def _sizes(
    sandbox: Sandbox, base: str, branch: str, files: list[ChangedFile]
) -> list[ChangedFile]:
    """`files` with each side's size, from `git cat-file --batch-check`."""
    specs: list[str] = []
    for f in files:
        specs.append(f"{base}:{f.old_path or f.path}")
        specs.append(f"refs/heads/{branch}:{f.path}")
    if not specs:
        return []
    known = [s for s in specs if "\n" not in s]
    result = await sandbox.exec(
        ["sh", "-c", _BLOBS_SCRIPT, "sizes", sandbox.workdir, "--sizes", *known], timeout_s=60.0
    )
    if result.exit_code != 0:
        raise SandboxError("could not read the sizes of the branch's files")
    lines = iter(result.stdout.splitlines())
    sizes: dict[str, int | None] = {}
    for spec in known:
        kind, _, size = next(lines, "").partition(" ")
        sizes[spec] = int(size) if kind == "blob" and size.isdigit() else None
    out: list[ChangedFile] = []
    for f, (before, after) in zip(files, zip(specs[::2], specs[1::2], strict=True), strict=True):
        out.append(
            ChangedFile(
                path=f.path,
                status=f.status,
                old_path=f.old_path,
                before_size=sizes.get(before) if f.status != "added" else None,
                after_size=sizes.get(after) if f.status != "deleted" else None,
            )
        )
    return out


def _refuse_newlines(specs: Sequence[str]) -> None:
    if any("\n" in s for s in specs):
        raise ValueError("a path with a newline cannot be read")


def _parse_batch(data: bytes, count: int) -> list[bytes | None]:
    """Parse `git cat-file --batch` output: per object `<sha> <type> <size>\\n<data>\\n`, or
    `<spec> missing\\n`."""
    blobs: list[bytes | None] = []
    pos = 0
    for _ in range(count):
        end = data.index(b"\n", pos)
        header = data[pos:end].split(b" ")
        pos = end + 1
        if len(header) == 3 and header[2].isdigit():
            size = int(header[2])
            blobs.append(data[pos : pos + size] if header[1] == b"blob" else None)
            pos += size + 1
        else:
            blobs.append(None)
    return blobs
