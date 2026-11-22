"""Per-run sandboxes holding a repo clone, worktrees for the nodes that write to it, and their
branches bundled for publishing."""

from agentic_sandbox.bundle import (
    BranchBundle,
    BranchHeads,
    EmptyBranchError,
    branch_heads,
    export_branch,
    import_bundles,
)
from agentic_sandbox.errors import SandboxError
from agentic_sandbox.fake import FakeSandbox, FakeSandboxManager
from agentic_sandbox.integrate import (
    IntegrationOutcome,
    MergeSource,
    integrate_branches,
    start_branches,
)
from agentic_sandbox.protocol import (
    ARTIFACT_NAME,
    DEFAULT_EXEC_TIMEOUT_S,
    MAX_OUTPUT_BYTES,
    MAX_PUT_FILE_BYTES,
    MAX_TAKE_FILE_BYTES,
    ExecResult,
    JobNetwork,
    Sandbox,
    SandboxManager,
)
from agentic_sandbox.refs import (
    BranchDiff,
    DiffFile,
    FileSlice,
    RefPathError,
    branch_diff,
    branch_has_commits,
    grep_tree,
    list_tree,
    show_file,
)
from agentic_sandbox.review import BranchNotFoundError
from agentic_sandbox.snapshot import Snapshot, snapshot_worktrees, wip_branch
from agentic_sandbox.source import COMMIT_ID, RepoSource, clone_shallow
from agentic_sandbox.worktree import (
    AGENT_IDENTITY,
    GIT_SAFETY,
    WRITE_FILE_SCRIPT,
    WRITE_NOT_A_FILE,
    WRITE_OUTSIDE,
    Worktree,
    add_worktree,
    branch_name,
)

__all__ = [
    "AGENT_IDENTITY",
    "ARTIFACT_NAME",
    "COMMIT_ID",
    "DEFAULT_EXEC_TIMEOUT_S",
    "GIT_SAFETY",
    "MAX_OUTPUT_BYTES",
    "MAX_PUT_FILE_BYTES",
    "MAX_TAKE_FILE_BYTES",
    "WRITE_FILE_SCRIPT",
    "WRITE_NOT_A_FILE",
    "WRITE_OUTSIDE",
    "BranchBundle",
    "BranchDiff",
    "BranchHeads",
    "BranchNotFoundError",
    "DiffFile",
    "EmptyBranchError",
    "ExecResult",
    "FakeSandbox",
    "FakeSandboxManager",
    "FileSlice",
    "IntegrationOutcome",
    "JobNetwork",
    "MergeSource",
    "RefPathError",
    "RepoSource",
    "Sandbox",
    "SandboxError",
    "SandboxManager",
    "Snapshot",
    "Worktree",
    "add_worktree",
    "branch_diff",
    "branch_has_commits",
    "branch_heads",
    "branch_name",
    "clone_shallow",
    "export_branch",
    "grep_tree",
    "import_bundles",
    "integrate_branches",
    "list_tree",
    "show_file",
    "snapshot_worktrees",
    "start_branches",
    "wip_branch",
]
