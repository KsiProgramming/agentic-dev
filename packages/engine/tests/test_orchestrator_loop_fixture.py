"""The looped orchestrator run the web's console tests fold
(`schemas/fixtures/orchestrator-loop-run.json`, 6.9): a loop around a writing orchestrator and a
reviewer. Iteration 1 plans a and b and the reviewer asks for changes; iteration 2 plans c on
top of the merged work and the reviewer approves. The web reads the engine's real event shapes,
so a change on either side fails a test.

Set `UPDATE_FIXTURES=1` to write the file again after a deliberate change to the events."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_engine.events import InMemoryEventSink
from agentic_runtime import Message
from agentic_runtime.fake import CallTool, Delay, Script

from .test_orchestrator import HUB, Desk, plan
from .test_orchestrator_integrate import Merger, run
from .test_orchestrator_loop import ReviewedTeam, review_loop

FIXTURE = (
    Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "orchestrator-loop-run.json"
)
RUN_ID = "00000000-0000-4000-8000-000000000069"
START = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
REVIEW = "CHANGES: b has no test for the empty case."


def writer(task: str, delay: float) -> Script:
    return [
        Delay(delay),
        CallTool("repo.write_file", {"path": f"{task}.py", "content": "x"}),
        Message(text=f"Fixed {task}."),
    ]


async def record() -> dict[str, Any]:
    flow = review_loop()
    desk = Desk()
    team = ReviewedTeam(
        [
            plan("a", "b", reason="One task per module."),
            plan("c", reason="Add the test the review asked for."),
        ],
        [REVIEW, "OK"],
        scripts={
            f"{HUB}.a": writer("a", 0.05),
            f"{HUB}.b": writer("b", 0.2),
            f"{HUB}.c": writer("c", 0.05),
        },
        tools=desk,
    )
    sink = InMemoryEventSink()
    merger = Merger()
    result = await run(flow, team, merger, sink, desk)
    assert result.status == "completed", result.results[HUB].error
    assert merger.started == [[f"{HUB}.c"]]
    events = [
        {
            "run_id": RUN_ID,
            "seq": e.seq,
            "type": e.type,
            "node_id": e.node_id,
            "payload": e.payload,
            # One second per event, so durations in the web's tests are fixed.
            "created_at": (START + timedelta(seconds=e.seq)).isoformat().replace("+00:00", "Z"),
        }
        for e in sink.events
    ]
    return {"spec": flow.model_dump(mode="json", exclude_none=True), "events": events}


async def test_the_web_fixture_is_the_engines_events() -> None:
    recorded = await record()
    text = json.dumps(recorded, indent=2) + "\n"
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.exists(), "run with UPDATE_FIXTURES=1 to write the fixture"
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored == recorded, "the looped orchestrator's events changed: UPDATE_FIXTURES=1"
