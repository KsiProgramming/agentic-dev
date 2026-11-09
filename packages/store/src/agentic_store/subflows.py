"""The stored workflows a spec calls (6.5): read from the workspace before a run or a check, and
kept with a run (`runs.subflows`) so it runs, resumes and reruns what it was created with.

The engine's checks are synchronous, so every version a spec calls, and those they call in turn,
is read first (`load_subflows`), and the engine resolves the spec from those copies.
"""

from collections.abc import Collection, Mapping
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import (
    PLATFORM_TOOLS,
    ExpandedWorkflow,
    WorkflowSpec,
    expand_workflow,
    parse_spec,
    resolve_from,
    subflow_key,
    subflow_refs,
)
from agentic_engine.spec.subflows import MAX_CALL_NESTING
from agentic_store.models import WorkflowVersion


async def load_subflows(
    session: AsyncSession, workspace_id: UUID, raw: object
) -> dict[str, JsonValue]:
    """The spec of each stored workflow version the decoded document `raw` calls, and those they
    call, by `subflow_key`, as deep as calls are resolved (`MAX_CALL_NESTING`). A version the
    workspace does not have is left out; the engine reports it."""
    found: dict[str, JsonValue] = {}
    wanted: set[tuple[str, int]] = set(subflow_refs(raw))
    for _ in range(MAX_CALL_NESTING + 1):
        wanted = {(w, v) for w, v in wanted if subflow_key(w, v) not in found}
        if not wanted:
            break
        query = select(
            WorkflowVersion.workflow_id, WorkflowVersion.version, WorkflowVersion.spec
        ).where(
            WorkflowVersion.workspace_id == workspace_id,
            tuple_(WorkflowVersion.workflow_id, WorkflowVersion.version).in_(sorted(wanted)),
        )
        rows = (await session.execute(query)).tuples()
        wanted = set()
        for workflow_id, version, spec in rows:
            found[subflow_key(workflow_id, version)] = spec
            wanted.update(subflow_refs(spec))
    return found


async def resolve_workflow(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    spec: WorkflowSpec,
    known_tools: Collection[str] = PLATFORM_TOOLS,
) -> ExpandedWorkflow:
    """`spec` with the workflows it calls resolved from the workspace (`expand_workflow`): the
    expanded spec, the copies a run keeps, and why it cannot run. A spec with no subflow reads
    nothing."""
    raw = spec.model_dump(mode="json", by_alias=True)
    if next(subflow_refs(raw), None) is None:
        return ExpandedWorkflow(spec)
    async with sessions() as session:
        documents = await load_subflows(session, workspace_id, raw)
    return expand_workflow(spec, resolve_from(documents), known_tools)


def run_spec(
    spec: Mapping[str, JsonValue], subflows: Mapping[str, JsonValue] | None
) -> WorkflowSpec:
    """A run's spec, expanded from the copies it was created with. They were checked then, so a
    call they do not hold is left unresolved, and the engine refuses to compile it."""
    parsed = parse_spec(spec)
    if not subflows:
        return parsed
    return expand_workflow(parsed, resolve_from(subflows)).spec
