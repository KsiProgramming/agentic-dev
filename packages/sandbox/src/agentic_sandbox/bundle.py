"""A writer's branch, taken out of the sandbox as a git bundle, so it can be pushed from the
worker (the sandbox has no network and never holds a credential).

The bundle holds only the branch's own commits: `<base>..<branch>`, where `<base>` is the clone's
`HEAD`, which every writer's worktree starts from. Whoever pushes it fetches `<base>` from the
remote first, then the bundle on top of it.
"""

import re
from dataclasses import dataclass
from uuid import uuid4

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import Sandbox
from agentic_sandbox.worktree import GIT_SAFETY

_NO_BRANCH = 8
_NO_COMMITS = 9
_SHA = re.compile(r"^[0-9a-f]{40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/][A-Za-z0-9._/-]*$")

# `$1` the branch, `$2` the bundle to write, `$3` the checkout (trusted by git although root owns
# it). Prints the base commit. The options hold no shell syntax.
_EXPORT_SCRIPT = f"""
checkout=$3
g() {{ git -c safe.directory="$checkout" {" ".join(GIT_SAFETY)} "$@"; }}
base=$(g rev-parse --verify -q 'HEAD^{{commit}}') || exit 1
g rev-parse --verify -q "refs/heads/$1" >/dev/null || exit {_NO_BRANCH}
[ "$(g rev-list --count "$base..refs/heads/$1")" -gt 0 ] || exit {_NO_COMMITS}
g bundle create -q "$2" "$base..refs/heads/$1" || exit 1
echo "$base"
"""


@dataclass(frozen=True)
class BranchBundle:
    branch: str
    # The commit the branch grows from (the clone's `HEAD`); the bundle's only prerequisite.
    base_sha: str
    data: bytes


async def export_branch(sandbox: Sandbox, branch: str) -> BranchBundle:
    """Bundle the commits `branch` has on top of the clone's `HEAD`. `sandbox` is the run's
    sandbox, not a worktree. Raises `SandboxError` if the branch does not exist or has no
    commits of its own, or if the bundle cannot be made or is too large."""
    if not _BRANCH.match(branch) or ".." in branch:
        raise ValueError(f"not a branch name: {branch!r}")
    path = f"{sandbox.staging_dir}/{uuid4().hex}.bundle"
    result = await sandbox.exec(
        ["sh", "-c", _EXPORT_SCRIPT, "export_branch", branch, path, sandbox.workdir],
        timeout_s=120.0,
    )
    if result.exit_code in (_NO_BRANCH, _NO_COMMITS):
        raise SandboxError(f"branch {branch} has no commits to publish")
    base = result.stdout.strip()
    if result.exit_code != 0 or not _SHA.match(base):
        raise SandboxError(f"could not bundle branch {branch}")
    return BranchBundle(branch=branch, base_sha=base, data=await sandbox.take_file(path))
