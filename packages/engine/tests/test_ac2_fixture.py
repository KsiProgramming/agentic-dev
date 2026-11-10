"""The AC-2 run the web's tests draw (`schemas/fixtures/ac2-run.json`, 6.8): the "Plan, build
and review" template run to its pull request, the reviewer sending the work back once. The web
draws the run map and the canvas from the same spec, so a change to either side's reading of
the engine's events fails a test.

Set `UPDATE_FIXTURES=1` to write the file again after a deliberate change to the events."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_engine.conformance import trace_mismatches
from agentic_engine.events import RunEvent

from .test_ac2 import Ac2Run

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "ac2-run.json"
RUN_ID = "00000000-0000-4000-8000-000000000068"
START = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


async def record() -> dict[str, Any]:
    run = Ac2Run()
    done = await run.to_the_end()
    assert done.status == "completed"
    assert trace_mismatches(run.spec.root, run.sink.events, run.spec.id) == []

    def at(seconds: float) -> str:
        return (START + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    def payload(e: RunEvent) -> dict[str, Any]:
        # A gate's expiry is counted from when the test ran; pin it to the fixed clock.
        ttl = e.payload.get("ttl_s")
        if e.type == "gate_waiting" and isinstance(ttl, int):
            return {**e.payload, "expires_at": at(e.seq + ttl)}
        return dict(e.payload)

    events = [
        {
            "run_id": RUN_ID,
            "seq": e.seq,
            "type": e.type,
            "node_id": e.node_id,
            "payload": payload(e),
            # One second per event, so durations in the web's tests are fixed.
            "created_at": at(e.seq),
        }
        for e in run.sink.events
    ]
    spec = run.spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"spec": spec, "events": events}


async def test_the_web_fixture_is_the_engines_events() -> None:
    recorded = await record()
    text = json.dumps(recorded, indent=2) + "\n"
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    assert FIXTURE.exists(), "run with UPDATE_FIXTURES=1 to write the fixture"
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored == recorded, "the AC-2 run's events changed: UPDATE_FIXTURES=1"
