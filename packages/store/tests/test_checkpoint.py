import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.graph import resume_workflow, run_workflow
from agentic_engine.spec import parse_spec
from agentic_runtime.fake import ECHO_USAGE, Delay, FakeRuntime
from agentic_store import open_checkpointer
from agentic_store.checkpoint import psycopg_conninfo

# psycopg's async driver cannot use the Proactor loop that Windows tests run on.
needs_selector_loop = pytest.mark.skipif(
    sys.platform == "win32", reason="psycopg async needs a selector loop"
)

SPEC = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "three-step-sequence.json"
)


class Step2Watch(InMemoryEventSink):
    def __init__(self) -> None:
        super().__init__()
        self.step2_started = asyncio.Event()

    async def emit(self, event: RunEvent) -> None:
        await super().emit(event)
        if event.type == "node_started" and event.node_id == "step-2":
            self.step2_started.set()


def test_psycopg_conninfo_drops_the_sqlalchemy_driver() -> None:
    url = "postgresql+asyncpg://agentic:s3cret@db:5432/agentic"
    assert psycopg_conninfo(url) == "postgresql://agentic:s3cret@db:5432/agentic"


@pytest.mark.integration
@needs_selector_loop
async def test_a_run_resumes_from_its_postgres_checkpoint(
    sessions: async_sessionmaker[AsyncSession], postgres_url: str
) -> None:
    """The saver on the tables revision 0006 creates keeps `step-1` across a lost attempt."""
    spec = parse_spec(json.loads(SPEC.read_text(encoding="utf-8")))
    run_id = uuid4()
    async with open_checkpointer(postgres_url) as checkpointer:
        first = FakeRuntime({"step-2": [Delay(60), ECHO_USAGE]})
        sink = Step2Watch()
        task = asyncio.create_task(
            run_workflow(spec, first, "go", run_id=run_id, sink=sink, checkpointer=checkpointer)
        )
        await asyncio.wait_for(sink.step2_started.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async with open_checkpointer(postgres_url) as checkpointer:
        second = FakeRuntime()
        result = await resume_workflow(
            spec,
            second,
            "go",
            run_id=run_id,
            sink=InMemoryEventSink(),
            checkpointer=checkpointer,
            next_seq=100,
            attempt=2,
        )

    assert [r.node_id for r in second.requests] == ["step-2", "step-3"]
    assert (result.status, result.order) == ("completed", ["step-1", "step-2", "step-3"])
