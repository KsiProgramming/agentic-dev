"""The subflow run the web's console tests fold (`schemas/fixtures/subflow-run.json`, 6.5): a
caller whose `agent_1` and root `main` the called workflow also has, so two of its nodes run
renamed. The fixture holds the caller's spec, its `calls` as `GET /runs/{id}` returns them, and
the run's events, so a change on either side fails a test.

Set `UPDATE_FIXTURES=1` to write the file again after a deliberate change to the events."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_engine.events import InMemoryEventSink
from agentic_engine.spec import call_documents

from .test_subflow import Recorder, agent, expanded, library, run, subflow, workflow

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "subflow-run.json"
RUN_ID = "00000000-0000-4000-8000-000000000065"
START = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

CHECKS: dict[str, Any] = {
    **workflow("checks", agent("agent_1", role="Reviewer"), agent("verdict", role="Judge")),
    "name": "Checks",
}
CALLER: dict[str, Any] = {
    **workflow(
        "caller",
        agent("agent_1", role="Planner"),
        subflow("review", "checks", 2),
        agent("summary", role="Writer"),
    ),
    "name": "Caller",
}


async def record() -> dict[str, Any]:
    for document in (CHECKS, CALLER):
        document["root"]["id"] = "main"
    spec = expanded(CALLER, library(CHECKS, version=2))
    sink = InMemoryEventSink()
    result = await run(spec, Recorder(), sink)
    assert result.status == "completed"
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
    return {
        "spec": spec.model_dump(mode="json", exclude_none=True),
        "calls": call_documents(spec.root),
        "events": events,
    }


async def test_the_web_fixture_is_the_engines_events() -> None:
    recorded = await record()
    text = json.dumps(recorded, indent=2) + "\n"
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    assert FIXTURE.exists(), "run with UPDATE_FIXTURES=1 to write the fixture"
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored == recorded, "the subflow's events changed: run with UPDATE_FIXTURES=1"
    assert recorded["calls"]["review"]["renamed"] == {
        "review-main": "main",
        "review-agent_1": "agent_1",
    }
