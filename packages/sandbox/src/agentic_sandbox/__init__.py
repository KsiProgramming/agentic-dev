"""Per-run sandboxes holding a repo clone, and worktrees for the nodes that write to it."""

from agentic_sandbox.errors import SandboxError
from agentic_sandbox.fake import FakeSandbox, FakeSandboxManager
from agentic_sandbox.protocol import (
    DEFAULT_EXEC_TIMEOUT_S,
    MAX_OUTPUT_BYTES,
    MAX_PUT_FILE_BYTES,
    ExecResult,
    Sandbox,
    SandboxManager,
)
from agentic_sandbox.source import RepoSource, clone_shallow
from agentic_sandbox.worktree import GIT_SAFETY, Worktree, add_worktree, branch_name

__all__ = [
    "DEFAULT_EXEC_TIMEOUT_S",
    "GIT_SAFETY",
    "MAX_OUTPUT_BYTES",
    "MAX_PUT_FILE_BYTES",
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
]
