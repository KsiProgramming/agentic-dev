"""Per-run sandboxes holding a repo clone, worktrees for the nodes that write to it, and their
branches bundled for publishing."""

from agentic_sandbox.bundle import BranchBundle, export_branch
from agentic_sandbox.errors import SandboxError
from agentic_sandbox.fake import FakeSandbox, FakeSandboxManager
from agentic_sandbox.protocol import (
    DEFAULT_EXEC_TIMEOUT_S,
    MAX_OUTPUT_BYTES,
    MAX_PUT_FILE_BYTES,
    MAX_TAKE_FILE_BYTES,
    ExecResult,
    Sandbox,
    SandboxManager,
)
from agentic_sandbox.source import RepoSource, clone_shallow
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
    "DEFAULT_EXEC_TIMEOUT_S",
    "GIT_SAFETY",
    "MAX_OUTPUT_BYTES",
    "MAX_PUT_FILE_BYTES",
    "MAX_TAKE_FILE_BYTES",
    "WRITE_FILE_SCRIPT",
    "WRITE_NOT_A_FILE",
    "WRITE_OUTSIDE",
    "BranchBundle",
    "ExecResult",
    "FakeSandbox",
    "FakeSandboxManager",
    "RepoSource",
    "Sandbox",
    "SandboxError",
    "SandboxManager",
    "Worktree",
    "add_worktree",
    "branch_name",
    "clone_shallow",
    "export_branch",
]
