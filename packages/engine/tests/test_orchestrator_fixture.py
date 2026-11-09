"""The orchestrator run the web's console tests fold (`schemas/fixtures/orchestrator-run.json`,
6.4): a writing orchestrator with a replan whose first round has a completed task, a failed one,
a dropped one and one that conflicts at integration, and whose second round completes. The web
reads the engine's real event shapes, so a change on either side fails a test.

Set `UPDATE_FIXTURES=1` to write the file again after a deliberate change to the events."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_engine.events import InMemoryEventSink
from agentic_runtime import Message
from agentic_runtime.fake import CallTool, Delay, Script

from .test_orchestrator import HUB, Desk, agent, plan, spec
from .test_orchestrator_integrate import Merger, run
from .test_orchestrator_replan import Replanner, replanning

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "orchestrator-run.json"
RUN_ID = "00000000-0000-4000-8000-000000000064"
START = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def writer(task: str, delay: float) -> Script:
    return [
        Delay(delay),
        CallTool("repo.write_file", {"path": f"{task}.py", "content": "x"}),
        Message(text=f"Fixed {task}."),
    ]


async def record() -> dict[str, Any]:
    flow = spec(
        agent("scan", instructions="List the modules."),
        replanning(
            agent("fixer", tools=["repo.write_file"]),
            max_rounds=1,
            max_workers=6,
            max_concurrency=3,
        ),
    )
    desk = Desk()
    team = Replanner(
        [
            plan("a", "b", "c", "d", reason="One task per module."),
            plan("b2", "c2", reason="Retry b and c apart from a."),
        ],
        # b fails first, so d never starts (dropped); a and c complete, c conflicts with a.
        fail=["b"],
        delays={"b": 0.05},
        scripts={
            f"{HUB}.a": writer("a", 0.2),
            f"{HUB}.c": writer("c", 0.4),
            f"{HUB}.b2": writer("b2", 0.05),
            f"{HUB}.c2": writer("c2", 0.2),
        },
        tools=desk,
    )
    sink = InMemoryEventSink()
    result = await run(flow, team, Merger(conflicts={"c": ["src/app.py"]}), sink, desk)
    assert result.status == "completed", result.results[HUB].error
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
    assert stored == recorded, "the orchestrator's events changed: run with UPDATE_FIXTURES=1"
