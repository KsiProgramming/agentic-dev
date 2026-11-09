"""An integration branch: several writers' branches merged into one, in a given order (6.3).

`integrate_branches` makes (or reuses) the worktree and branch `agent/<run>/<target>` from the
clone's `HEAD`, the base every writer's branch starts from, then merges each source branch into
it with `git merge --no-ff`, one merge commit each, as the agent identity. A source with no
commits past the base is `empty`; one already in the integration branch counts as merged, so a
call repeated after a crash merges nothing twice. A source that conflicts is aborted and listed
with its conflicting paths; the integration branch keeps every source merged before it, and the
sources after it are still merged.

Nothing is pushed and no source branch is changed. Repo content is data: git runs with
`GIT_SAFETY`, and nothing read here is executed.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.protocol import Sandbox
from agentic_sandbox.worktree import AGENT_IDENTITY, GIT_SAFETY, Worktree

_WRONG_BRANCH = 9
_MERGE_FAILED = 10

# `$1` the integration branch, `$2` its worktree, `$3` the checkout (trusted by git although root
# owns it), `$4` and `$5` the identity, then per source its branch and merge message. Prints, NUL
# separated, per source `merged`, `empty`, or `conflict` followed by its conflicting paths and an
# empty field, then `head` and the integration branch's tip. The options hold no shell syntax.
_INTEGRATE_SCRIPT = f"""
target=$1
tree=$2
checkout=$3
name=$4
email=$5
shift 5
g() {{
  git -c safe.directory="$checkout" -c user.name="$name" -c user.email="$email" \\
    {" ".join(GIT_SAFETY)} "$@"
}}
base=$(g -C "$checkout" rev-parse --verify -q 'HEAD^{{commit}}') || exit 1
if [ -e "$tree" ]; then
  [ "$(g -C "$tree" rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$target" ] || exit {_WRONG_BRANCH}
elif g -C "$checkout" rev-parse --verify -q "refs/heads/$target" >/dev/null; then
  g -C "$checkout" worktree add -q "$tree" "$target" || exit 1
else
  g -C "$checkout" worktree add -q -b "$target" "$tree" HEAD || exit 1
fi
if g -C "$tree" rev-parse --verify -q MERGE_HEAD >/dev/null; then
  g -C "$tree" merge --abort || exit 1
fi
while [ $# -gt 0 ]; do
  src=refs/heads/$1
  msg=$2
  shift 2
  if ! g -C "$tree" rev-parse --verify -q "$src" >/dev/null \\
     || g -C "$tree" merge-base --is-ancestor "$src" "$base"; then
    printf 'empty\\0'
  elif g -C "$tree" merge-base --is-ancestor "$src" HEAD; then
    printf 'merged\\0'
  elif g -C "$tree" merge -q --no-ff --no-verify --no-edit -m "$msg" "$src" >/dev/null 2>&1; then
    printf 'merged\\0'
  elif g -C "$tree" diff --quiet --diff-filter=U; then
    g -C "$tree" merge --abort >/dev/null 2>&1
    exit {_MERGE_FAILED}
  else
    printf 'conflict\\0'
    g -C "$tree" -c core.quotePath=false diff --name-only --diff-filter=U -z || exit 1
    printf '\\0'
    g -C "$tree" merge --abort || exit 1
  fi
done
printf 'head\\0%s\\0' "$(g -C "$tree" rev-parse HEAD)"
"""


@dataclass(frozen=True)
class MergeSource:
    """A branch to merge: the writer `key` whose branch it is (`agent/<run>/<key>`), and the
    message of its merge commit."""

    key: str
    message: str


@dataclass(frozen=True)
class IntegrationOutcome:
    """What `integrate_branches` did, by writer key, in the order the sources were given."""

    branch: str
    head: str
    merged: list[str] = field(default_factory=list[str])
    empty: list[str] = field(default_factory=list[str])
    conflicts: dict[str, list[str]] = field(default_factory=dict[str, list[str]])


async def integrate_branches(
    sandbox: Sandbox, run_id: UUID, target: str, sources: Sequence[MergeSource]
) -> IntegrationOutcome:
    """Merge the branches of `sources`, in order, into `agent/<run_id>/<target>` (made from the
    clone's `HEAD` if it does not exist). `sandbox` is the run's sandbox, not a worktree. Raises
    `SandboxError` if git fails other than by a conflict."""
    tree = Worktree.of(sandbox, run_id, target)
    args: list[str] = []
    for source in sources:
        branch = Worktree.of(sandbox, run_id, source.key).branch
        if "\0" in source.message:
            raise ValueError("a merge message cannot hold a NUL")
        args += [branch, source.message]
    argv = [
        "sh", "-c", _INTEGRATE_SCRIPT, "integrate_branches",
        tree.branch, tree.path, sandbox.workdir, *AGENT_IDENTITY, *args,
    ]  # fmt: skip
    result = await sandbox.exec(argv, timeout_s=300.0)
    if result.exit_code == _WRONG_BRANCH:
        raise SandboxError(f"the worktree of {target} is on another branch")
    if result.exit_code == _MERGE_FAILED:
        raise SandboxError(f"git could not merge into {tree.branch}")
    if result.exit_code != 0 or result.truncated:
        raise SandboxError(f"could not build the integration branch {tree.branch}")
    return _parse(tree.branch, result.stdout, [s.key for s in sources])


def _parse(branch: str, stdout: str, keys: list[str]) -> IntegrationOutcome:
    fields = iter(stdout.split("\0"))
    merged: list[str] = []
    empty: list[str] = []
    conflicts: dict[str, list[str]] = {}
    for key in keys:
        status = next(fields, "")
        if status == "merged":
            merged.append(key)
        elif status == "empty":
            empty.append(key)
        elif status == "conflict":
            conflicts[key] = list(iter(lambda: next(fields, ""), ""))
        else:
            raise SandboxError(f"could not read how {branch} was built")
    label, head = next(fields, ""), next(fields, "")
    if label != "head" or len(head) != 40:
        raise SandboxError(f"could not read how {branch} was built")
    return IntegrationOutcome(
        branch=branch, head=head, merged=merged, empty=empty, conflicts=conflicts
    )
