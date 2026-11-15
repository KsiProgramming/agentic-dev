"""A writer's branch, taken out of the sandbox as a git bundle: to push it from the worker (the
sandbox has no network and never holds a credential), and to save it outside the sandbox when its
step completes, so a fresh sandbox can get it back (12.2).

The bundle holds only the branch's own commits: `<base>..<branch>`, where `<base>` is the clone's
`HEAD`, which every writer's worktree starts from. Whoever pushes it fetches `<base>` from the
remote first, then the bundle on top of it. A run's later sandboxes are cloned at the same
`<base>` (`clone_shallow(..., at=...)`), so its saved bundles fetch into them as they are
(`import_bundles`).
"""

import asyncio
import contextlib
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import Sandbox
from agentic_sandbox.worktree import GIT_SAFETY

_NO_BRANCH = 8
_NO_COMMITS = 9
_SHA = re.compile(r"^[0-9a-f]{40}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/][A-Za-z0-9._/-]*$")
IMPORT_TIMEOUT_S = 120.0

# `$1` the branch, `$2` the bundle to write, `$3` the checkout (trusted by git although root owns
# it). Prints the base commit, the branch's tip and how many commits it has on top of the base.
# The options hold no shell syntax.
_EXPORT_SCRIPT = f"""
checkout=$3
g() {{ git -c safe.directory="$checkout" {" ".join(GIT_SAFETY)} "$@"; }}
base=$(g rev-parse --verify -q 'HEAD^{{commit}}') || exit 1
head=$(g rev-parse --verify -q "refs/heads/$1^{{commit}}") || exit {_NO_BRANCH}
count=$(g rev-list --count "$base..$head") || exit 1
[ "$count" -gt 0 ] || exit {_NO_COMMITS}
g bundle create -q "$2" "$base..refs/heads/$1" || exit 1
echo "$base $head $count"
"""

# `$1` the checkout; `$2` a ref prefix. Prints the clone's `HEAD`, then each branch under the
# prefix with its tip.
_HEADS_SCRIPT = f"""
checkout=$1 prefix=$2
g() {{ git -c safe.directory="$checkout" {" ".join(GIT_SAFETY)} "$@"; }}
g rev-parse --verify -q 'HEAD^{{commit}}' || exit 1
g for-each-ref --format='%(refname:short) %(objectname)' "refs/heads/$prefix"
"""


@dataclass(frozen=True)
class BranchBundle:
    branch: str
    # The commit the branch grows from (the clone's `HEAD`); the bundle's only prerequisite.
    base_sha: str
    data: bytes
    # The branch's tip, and how many commits it has on top of `base_sha`.
    head_sha: str = ""
    commits: int = 0


class EmptyBranchError(SandboxError):
    """The branch does not exist, or has no commits on top of the clone's `HEAD`."""


@dataclass(frozen=True)
class BranchHeads:
    """The clone's `HEAD` (`base`) and the tip of each branch under a prefix."""

    base: str
    branches: dict[str, str]


async def export_branch(sandbox: Sandbox, branch: str) -> BranchBundle:
    """Bundle the commits `branch` has on top of the clone's `HEAD`. `sandbox` is the run's
    sandbox, not a worktree. Raises `EmptyBranchError` if the branch does not exist or has no
    commits of its own, and `SandboxError` if the bundle cannot be made or is too large."""
    _check_branch(branch)
    path = f"{sandbox.staging_dir}/{uuid4().hex}.bundle"
    result = await sandbox.exec(
        ["sh", "-c", _EXPORT_SCRIPT, "export_branch", branch, path, sandbox.workdir],
        timeout_s=120.0,
    )
    if result.exit_code in (_NO_BRANCH, _NO_COMMITS):
        raise EmptyBranchError(f"branch {branch} has no commits to publish")
    parts = result.stdout.split()
    if result.exit_code != 0 or len(parts) != 3 or not all(map(_SHA.match, parts[:2])):
        raise SandboxError(f"could not bundle branch {branch}")
    base, head, count = parts
    return BranchBundle(
        branch=branch,
        base_sha=base,
        data=await sandbox.take_file(path),
        head_sha=head,
        commits=int(count),
    )


async def branch_heads(sandbox: Sandbox, prefix: str) -> BranchHeads:
    """The clone's `HEAD` and the tip of each branch whose name starts with `prefix` (e.g.
    `agent/<run>/`). Raises `SandboxError` if git fails."""
    _check_branch(prefix)
    result = await sandbox.exec(
        ["sh", "-c", _HEADS_SCRIPT, "branch_heads", sandbox.workdir, prefix], timeout_s=30.0
    )
    lines = result.stdout.splitlines()
    if result.exit_code != 0 or not lines or not _SHA.match(lines[0]):
        raise SandboxError("could not list the run's branches")
    branches = dict(line.split(" ", 1) for line in lines[1:] if " " in line)
    return BranchHeads(base=lines[0], branches=branches)


async def import_bundles(clone: Path, bundles: Sequence[BranchBundle]) -> None:
    """Fetch each bundle into the clone at `clone` (on this host, before it is copied into a
    sandbox) as `refs/heads/<branch>`. Each bundle's base must be the clone's `HEAD`. Raises
    `SandboxError` if one cannot be fetched."""
    if not bundles:
        return
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    with tempfile.TemporaryDirectory(prefix="agentic-bundles-") as scratch:
        for index, bundle in enumerate(bundles):
            _check_branch(bundle.branch)
            path = Path(scratch) / f"{index}.bundle"
            await asyncio.to_thread(path.write_bytes, bundle.data)
            ref = f"refs/heads/{bundle.branch}"
            argv = [
                "git", "-C", str(clone), *GIT_SAFETY,
                "fetch", "-q", "--no-tags", "--update-head-ok", str(path), f"+{ref}:{ref}",
            ]  # fmt: skip
            error = f"could not restore branch {bundle.branch}"
            await _run(argv, env, error, hide=(scratch, clone))


async def _run(
    argv: list[str], env: dict[str, str], error: str, *, hide: Sequence[str | Path] = ()
) -> None:
    """Run git; on failure raise `SandboxError` with `error` and git's last line, the host paths
    in `hide` replaced."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError as e:
        raise SandboxError("git is not available on this worker") from e
    try:
        async with asyncio.timeout(IMPORT_TIMEOUT_S):
            _, stderr = await proc.communicate()
    except TimeoutError:
        raise SandboxError(f"{error}: git took too long") from None
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    if proc.returncode != 0:
        lines = [ln for ln in stderr.decode("utf-8", errors="replace").splitlines() if ln.strip()]
        detail = lines[-1].removeprefix("fatal:").strip() if lines else "git failed"
        for path in hide:
            for spelling in {str(path), Path(path).as_posix()}:
                detail = detail.replace(spelling, "<path>")
        raise SandboxError(f"{error}: {detail}")


def _check_branch(branch: str) -> None:
    if not BRANCH_PATTERN.match(branch) or ".." in branch:
        raise ValueError(f"not a branch name: {branch!r}")
