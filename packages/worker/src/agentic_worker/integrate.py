"""The `BranchIntegrator` of a run with a repo (6.3): an orchestrator's completed task branches
merged into its integration branch, `agent/<run>/<orchestrator>`, in the run's sandbox."""

import logging
from collections.abc import Sequence
from uuid import UUID

from agentic_engine.integrate import Integration, IntegrationError, MergeRequest
from agentic_sandbox import MergeSource, Sandbox, SandboxError, integrate_branches

log = logging.getLogger("agentic_worker")


class SandboxIntegrator:
    """Implements `BranchIntegrator` over `sandbox` for run `run_id`."""

    def __init__(self, sandbox: Sandbox, run_id: UUID) -> None:
        self._sandbox = sandbox
        self._run_id = run_id

    async def integrate(self, orchestrator_id: str, sources: Sequence[MergeRequest]) -> Integration:
        merges = [MergeSource(key=s.key, message=s.message) for s in sources]
        try:
            outcome = await integrate_branches(self._sandbox, self._run_id, orchestrator_id, merges)
        except SandboxError as e:
            raise IntegrationError(str(e)) from e
        log.info(
            "run %s: %s merged %d task branches into %s (%d conflicts)",
            self._run_id,
            orchestrator_id,
            len(outcome.merged),
            outcome.branch,
            len(outcome.conflicts),
        )
        return Integration(
            branch=outcome.branch,
            head=outcome.head,
            merged=outcome.merged,
            empty=outcome.empty,
            conflicts=outcome.conflicts,
        )
