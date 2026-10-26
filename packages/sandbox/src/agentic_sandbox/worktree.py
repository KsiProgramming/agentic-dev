"""One git worktree and branch per writer node, inside a run's sandbox.

A writer node gets `<worktrees_dir>/<node-id>`, a worktree of the run's clone on the new branch
`agent/<run-id>/<node-id>`, made from the clone's `HEAD`. Its tools see the worktree as their
sandbox (`Worktree`), so the node reads its own writes and never touches the shared checkout or
another writer's files. Nothing is pushed: the sandbox has no network.

Repo content is data: every git command runs with hooks, fsmonitor and signing off
(`GIT_SAFETY`), and the sandbox reads no system or user git config, so neither the repo nor the
host can make git run code.
"""

import logging
import re
from collections.abc import Sequence
from uuid import UUID

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import DEFAULT_EXEC_TIMEOUT_S, ExecResult, Sandbox

log = logging.getLogger("agentic_sandbox")

BRANCH_PREFIX = "agent"
GIT_SAFETY: tuple[str, ...] = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "commit.gpgsign=false",
    "-c", "tag.gpgsign=false",
)  # fmt: skip
"""`git` options every command in a sandbox runs with."""
AGENT_IDENTITY = ("agentic-dev agent", "agent@agentic-dev.invalid")
"""The name and email git records for agents' commits and ref updates. Every git command that
writes a ref must set it: without one, git asks DNS for the host's full name, which in a sandbox
with no network takes seconds to time out."""

# The spec's node id pattern: lowercase, ref- and path-safe.
_NODE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_WRONG_BRANCH = 9

WRITE_OUTSIDE = 4
WRITE_NOT_A_FILE = 5
WRITE_FILE_SCRIPT = """
staged=$2
fail() { rm -f -- "$staged"; exit "$1"; }
root=$(pwd -P)
dir=$(dirname -- "$1")
name=$(basename -- "$1")
probe=$dir
while [ ! -e "$probe" ] && [ ! -L "$probe" ]; do probe=$(dirname -- "$probe"); done
[ -d "$probe" ] || fail 5
cd -P -- "$probe" 2>/dev/null || fail 4
case "$(pwd -P)/" in "$root"/*) ;; *) fail 4 ;; esac
cd -- "$root" || fail 1
mkdir -p -- "$dir" 2>/dev/null || fail 5
cd -P -- "$dir" 2>/dev/null || fail 4
case "$(pwd -P)/" in "$root"/*) ;; *) fail 4 ;; esac
[ -L "$name" ] && fail 4
[ -d "$name" ] && fail 5
mv -f -- "$staged" "./$name" || fail 1
"""
"""Moves the staged file `$2` (from `put_file`) to the path `$1`, relative to the current
directory (a worktree), creating its parent directories. The deepest part of the parent that
exists, and then the parent itself, must resolve inside the worktree, and the target must not be
a symlink or a directory, so a write never leaves it. The staged file is removed if the write is
refused: exit `WRITE_OUTSIDE` for a path that leaves the worktree, `WRITE_NOT_A_FILE` for a
directory or file in the way."""

# `$1` branch, `$2` worktree path, `$3` the checkout (trusted by git although root owns it), `$4`
# and `$5` the identity. A worktree that already exists on the branch is reused. The options hold
# no shell syntax.
_ADD_SCRIPT = f"""
if [ -e "$2" ]; then
  [ "$(git -C "$2" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$1" ] && exit 0
  exit {_WRONG_BRANCH}
fi
git -c safe.directory="$3" -c user.name="$4" -c user.email="$5" {" ".join(GIT_SAFETY)} \\
  worktree add -q -b "$1" "$2" HEAD
"""


def branch_name(run_id: UUID, node_id: str) -> str:
    """The branch a writer node commits on: `agent/<run-id>/<node-id>`."""
    return f"{BRANCH_PREFIX}/{run_id}/{node_id}"


class Worktree:
    """A writer node's worktree, seen as a `Sandbox` whose `workdir` is the worktree. Commands
    run in it by default; staged files and the worktrees directory are the sandbox's."""

    def __init__(self, sandbox: Sandbox, path: str, branch: str) -> None:
        self._sandbox = sandbox
        self.path = path
        self.branch = branch

    @classmethod
    def of(cls, sandbox: Sandbox, run_id: UUID, node_id: str) -> "Worktree":
        """Where `node_id`'s worktree goes, and its branch; `add_worktree` creates it."""
        if not _NODE_ID.match(node_id):
            raise ValueError(f"not a node id: {node_id!r}")
        return cls(sandbox, f"{sandbox.worktrees_dir}/{node_id}", branch_name(run_id, node_id))

    @property
    def workdir(self) -> str:
        return self.path

    @property
    def worktrees_dir(self) -> str:
        return self._sandbox.worktrees_dir

    async def exec(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
        cwd: str | None = None,
    ) -> ExecResult:
        return await self._sandbox.exec(argv, timeout_s=timeout_s, cwd=cwd or self.path)

    async def put_file(self, data: bytes) -> str:
        return await self._sandbox.put_file(data)

    @property
    def staging_dir(self) -> str:
        return self._sandbox.staging_dir

    async def take_file(self, path: str) -> bytes:
        return await self._sandbox.take_file(path)


async def add_worktree(sandbox: Sandbox, run_id: UUID, node_id: str) -> Worktree:
    """The worktree of `node_id` on `agent/<run-id>/<node-id>`, created from the clone's `HEAD`
    unless it already exists. Raises `SandboxError` if git cannot create it."""
    tree = Worktree.of(sandbox, run_id, node_id)
    argv = [
        "sh", "-c", _ADD_SCRIPT, "add_worktree",
        tree.branch, tree.path, sandbox.workdir, *AGENT_IDENTITY,
    ]  # fmt: skip
    result = await sandbox.exec(argv)
    if result.exit_code == _WRONG_BRANCH:
        raise SandboxError(f"the worktree of node {node_id} is on another branch")
    if result.exit_code != 0:
        log.warning("git worktree add for %s failed: %s", tree.branch, result.stderr.strip())
        raise SandboxError(f"could not create the worktree of node {node_id}")
    log.info("worktree for %s ready", tree.branch)
    return tree
