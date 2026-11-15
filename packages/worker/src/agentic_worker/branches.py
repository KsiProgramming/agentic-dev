"""The `BranchSaver` a run's attempt gives the engine (12.2): it saves the run's writer and
integration branches from its sandbox to Postgres as git bundles, each time its tip moved."""

import asyncio
import logging
from collections.abc import Collection
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.branches import BranchSaved, BranchSaveFailed, BranchSaves
from agentic_sandbox import (
    EmptyBranchError,
    Sandbox,
    SandboxError,
    branch_heads,
    branch_name,
    export_branch,
)
from agentic_store import BundleTooLargeError, list_saved_branches, save_branch

log = logging.getLogger("agentic_worker")


class SandboxBranchSaver:
    """Saves the branches `agent/<run>/…` of the run's `sandbox`. A branch is bundled only when
    its tip differs from the one saved last (or that last failed to save); one with no commits of
    its own is skipped. `integrations` are the orchestrators whose tasks write: their own branch
    is an integration branch. Saves run one at a time, as steps end concurrently."""

    def __init__(
        self,
        sandbox: Sandbox,
        sessions: async_sessionmaker[AsyncSession],
        run_id: UUID,
        integrations: Collection[str],
    ) -> None:
        self._sandbox = sandbox
        self._sessions = sessions
        self._run_id = run_id
        self._integrations = frozenset(integrations)
        self._prefix = branch_name(run_id, "")
        self._seen: dict[str, str] | None = None  # branch → the tip last saved or tried
        self._lock = asyncio.Lock()

    async def save(self) -> BranchSaves:
        async with self._lock:
            if self._seen is None:
                saved = await list_saved_branches(self._sessions, self._run_id)
                self._seen = {s.branch: s.head_sha for s in saved}
            try:
                heads = await branch_heads(self._sandbox, self._prefix)
            except SandboxError as e:
                log.warning("run %s: cannot list its branches to save them: %s", self._run_id, e)
                return BranchSaves()
            saves = BranchSaves()
            for branch, head in sorted(heads.branches.items()):
                if self._seen.get(branch) != head:
                    await self._save(branch, head, saves)
            return saves

    async def _save(self, branch: str, head: str, saves: BranchSaves) -> None:
        assert self._seen is not None
        key = branch.removeprefix(self._prefix)
        kind = "integration" if key in self._integrations else "writer"
        try:
            bundle = await export_branch(self._sandbox, branch)
            row = await save_branch(self._sessions, self._run_id, key, kind, bundle)
        except EmptyBranchError:
            self._seen[branch] = head
            return
        except (SandboxError, BundleTooLargeError) as e:
            log.warning("run %s: branch %s not saved: %s", self._run_id, branch, e)
            self._seen[branch] = head
            saves.failed.append(BranchSaveFailed(key=key, branch=branch, error=str(e)))
            return
        self._seen[branch] = bundle.head_sha
        if row is not None:
            saves.saved.append(
                BranchSaved(
                    key=key,
                    branch=branch,
                    kind=row.kind,
                    version=row.version,
                    head=row.head_sha,
                    commits=row.commits,
                    size=row.size,
                )
            )
