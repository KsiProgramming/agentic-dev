"""A writer's uncommitted work, kept when its run fails or is cancelled (12.3).

`snapshot_worktrees` finds each writer worktree of a run (on `agent/<run>/<key>`) with changes
it has not committed, tracked or untracked, and records them as one commit on top of the
worktree's `HEAD`, on the branch `wip/<run>/<key>`. It works through a temporary index, so the
worktree, its index and its branch are left exactly as they were. `wip/` is outside `agent/`:
nothing restores, merges or pushes it; the worker bundles it like any branch
(`export_branch`), and the console shows what it changed.

Repo content is data: git runs with `GIT_SAFETY`, and nothing read here is executed.
"""

from dataclasses import dataclass
from uuid import UUID

from agentic_sandbox.bundle import BRANCH_PATTERN
from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import Sandbox
from agentic_sandbox.worktree import AGENT_IDENTITY, BRANCH_PREFIX, GIT_SAFETY

WIP_PREFIX = "wip"
WIP_MESSAGE = "Uncommitted work when the run ended"

# `$1` the checkout (trusted by git although root owns it), `$2` the writers' branch prefix,
# `$3` the wip branch prefix, `$4` and `$5` the identity, `$6` a scratch index path, `$7` the
# message. Prints `<key> <commit>` for each worktree it recorded. The options hold no shell
# syntax.
_SNAPSHOT_SCRIPT = f"""
checkout=$1 prefix=$2 wip=$3 name=$4 email=$5 index=$6 message=$7
g() {{
  git -c safe.directory="$checkout" -c user.name="$name" -c user.email="$email" \\
    {" ".join(GIT_SAFETY)} "$@"
}}
trees=$(g worktree list --porcelain) || exit 1
tree=
printf '%s\\n' "$trees" | while IFS= read -r line; do
  case $line in
    "worktree "*) tree=${{line#worktree }} ;;
    "branch refs/heads/$prefix"*)
      key=${{line#"branch refs/heads/$prefix"}}
      changed=$(g -C "$tree" status --porcelain --untracked-files=all) || exit 1
      [ -n "$changed" ] || continue
      rm -f "$index"
      GIT_INDEX_FILE=$index g -C "$tree" read-tree HEAD || exit 1
      GIT_INDEX_FILE=$index g -C "$tree" add -A -- . || exit 1
      snapshot=$(GIT_INDEX_FILE=$index g -C "$tree" write-tree) || exit 1
      rm -f "$index"
      commit=$(g -C "$tree" commit-tree "$snapshot" -p HEAD -m "$message") || exit 1
      g update-ref "refs/heads/$wip$key" "$commit" || exit 1
      echo "$key $commit"
      ;;
  esac
done
"""


@dataclass(frozen=True)
class Snapshot:
    """A writer's uncommitted work: its key, the branch it was recorded on and the commit."""

    key: str
    branch: str
    commit: str


def wip_branch(run_id: UUID, key: str) -> str:
    """The branch a writer's uncommitted work is recorded on: `wip/<run-id>/<key>`."""
    return f"{WIP_PREFIX}/{run_id}/{key}"


async def snapshot_worktrees(sandbox: Sandbox, run_id: UUID) -> list[Snapshot]:
    """Record the uncommitted work of each of the run's writer worktrees that has some, on
    `wip/<run>/<key>`, without changing the worktree or its branch. `sandbox` is the run's
    sandbox, not a worktree. Raises `SandboxError` if git fails."""
    prefix = f"{BRANCH_PREFIX}/{run_id}/"
    name, email = AGENT_IDENTITY
    result = await sandbox.exec(
        [
            "sh", "-c", _SNAPSHOT_SCRIPT, "snapshot_worktrees",
            sandbox.workdir, prefix, f"{WIP_PREFIX}/{run_id}/", name, email,
            f"{sandbox.staging_dir}/wip.index", WIP_MESSAGE,
        ],
        timeout_s=120.0,
    )  # fmt: skip
    if result.exit_code != 0:
        raise SandboxError("could not record the writers' uncommitted work")
    snapshots: list[Snapshot] = []
    for line in result.stdout.splitlines():
        key, _, commit = line.partition(" ")
        branch = wip_branch(run_id, key)
        if not BRANCH_PATTERN.match(branch) or len(commit) != 40:
            raise SandboxError("could not record the writers' uncommitted work")
        snapshots.append(Snapshot(key=key, branch=branch, commit=commit))
    return snapshots
