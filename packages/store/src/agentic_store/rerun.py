"""Rerunning a run: a new run with the same workflow spec, input, repo and workspace, linked to
the original by `rerun_of`. The original is never changed (its log is append-only).

A rerun from a step (12.4) starts at one of the original's top-level steps instead, from its
checkpoint before that step and with its code as it was then (`agentic_engine.graph.fork`,
`agentic_store.branches.rerun_branches`), with that step's parameters edited at most."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.graph import steps_before
from agentic_engine.spec import parse_spec
from agentic_engine.spec.ops import SetParam, apply_ops
from agentic_store.approvals import RunNotFoundError
from agentic_store.audit import audit, usd
from agentic_store.branches import (
    RerunBranchesError,
    has_uncommitted,
    last_started_step,
    rerun_branches,
)
from agentic_store.cancel import ENDED_STATUSES
from agentic_store.models import Run
from agentic_store.policy import run_policy
from agentic_store.subflows import run_spec


class RunNotEndedError(Exception):
    """The run has not ended yet; only an ended run can be rerun."""


class StepNotRerunnableError(Exception):
    """The run cannot be rerun from this step: it never got there, its code before it is gone
    or was saved before 12.4, or it left no uncommitted work there to start from."""


@dataclass(frozen=True)
class RerunFromStep:
    """Rerun from the top-level step `node_id` (12.4), with its parameters `set_params` (path
    and value, as `setParam` takes them) and, if `use_wip`, the uncommitted work it left."""

    node_id: str
    set_params: Sequence[tuple[str, JsonValue]] = field(
        default_factory=tuple[tuple[str, JsonValue], ...]
    )
    use_wip: bool = False


async def create_rerun(
    sessions: async_sessionmaker[AsyncSession],
    run_id: UUID,
    budget_usd: Decimal | None = None,
    from_step: RerunFromStep | None = None,
) -> UUID:
    """Insert a `queued` copy of the ended run `run_id` (its spec, input, repo, workspace,
    template and template options, the workflow version it ran and the copies of the workflows it
    calls, so it runs the same versions) with `rerun_of` set to it,
    and return the new run's id. Raises `RunNotFoundError`, or `RunNotEndedError` if the run is
    still queued, running or waiting. The new run gets the workspace's policy as it is now, not
    the original's, with `budget_usd` as its budget if given, and `PolicyViolationError` is
    raised if the spec is above it. The original's spend does not count toward it.

    With `from_step` the new run starts at that top-level step (12.4): its spec is the
    original's with the step's parameters set, it keeps the original's base commit, and
    `rerun_from` records the step, `use_wip` and the paths edited (never their values). Raises
    `StepNotFoundError` for a node that is not a top-level step, `OpError` for a parameter that
    cannot be set, and `StepNotRerunnableError` when the run never reached the step, its code
    before it cannot be restored, or `use_wip` finds no uncommitted work there."""
    new_id = uuid4()
    async with sessions.begin() as session:
        # An ended run never changes again, so it needs no lock while it is copied.
        original = await session.get(Run, run_id)
        if original is None:
            raise RunNotFoundError(f"run {run_id} not found")
        if original.status not in ENDED_STATUSES:
            raise RunNotEndedError(f"run {run_id} has not ended ({original.status})")
        spec = original.spec
        rerun_from: dict[str, JsonValue] | None = None
        if from_step is not None:
            spec = _edited(original.spec, from_step)
            await _check_step(sessions, original, from_step)
            edited: list[JsonValue] = [path for path, _ in from_step.set_params]
            rerun_from = {
                "node_id": from_step.node_id,
                "use_wip": from_step.use_wip,
                "edited": edited,
            }
        policy = await run_policy(
            session,
            original.workspace_id,
            run_spec(spec, original.subflows),
            budget_usd,
        )
        session.add(
            Run(
                id=new_id,
                workspace_id=original.workspace_id,
                status="queued",
                spec=spec,
                policy=policy.model_dump(mode="json"),
                input=original.input,
                repo=original.repo,
                repo_url=original.repo_url,
                template_id=original.template_id,
                template_parameters=original.template_parameters,
                workflow_id=original.workflow_id,
                workflow_version=original.workflow_version,
                subflows=original.subflows,
                rerun_of=original.id,
                rerun_from=rerun_from,
                base_sha=original.base_sha if from_step is not None else None,
                trigger="rerun",
                branch=original.repo.get("ref") if original.repo else None,
            )
        )
        audit(
            session,
            original.workspace_id,
            "run.rerun",
            run_id=new_id,
            details={
                "rerun_of": str(original.id),
                "template_id": original.template_id,
                "repo_url": original.repo_url,
                "budget_usd": usd(policy.budget_usd),
                **({"from": rerun_from} if rerun_from is not None else {}),
            },
        )
    return new_id


def _edited(spec: dict[str, JsonValue], step: RerunFromStep) -> dict[str, JsonValue]:
    """`spec` with the step's parameters set; raises `StepNotFoundError` or `OpError`."""
    steps_before(parse_spec(spec), step.node_id)
    if not step.set_params:
        return spec
    ops = [
        SetParam(op="setParam", node_id=step.node_id, path=path, value=value)
        for path, value in step.set_params
    ]
    return cast(dict[str, JsonValue], apply_ops(spec, ops))


async def _check_step(
    sessions: async_sessionmaker[AsyncSession], original: Run, step: RerunFromStep
) -> None:
    """Raise `StepNotRerunnableError` unless the run reached the step, its code before it can
    be restored and, with `use_wip`, the step left uncommitted work."""
    spec = run_spec(original.spec, original.subflows)
    if await last_started_step(sessions, original.id, [step.node_id]) is None:
        raise StepNotRerunnableError(f"the run never reached step {step.node_id!r}")
    if step.use_wip and not await has_uncommitted(sessions, original.id, step.node_id):
        raise StepNotRerunnableError(f"step {step.node_id!r} left no uncommitted work")
    try:
        await rerun_branches(
            sessions,
            original.id,
            uuid4(),
            steps_before(spec, step.node_id),
            step.node_id if step.use_wip else None,
            with_data=False,
        )
    except RerunBranchesError as e:
        raise StepNotRerunnableError(str(e)) from e
