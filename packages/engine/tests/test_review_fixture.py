"""The review run the web's tests draw (`schemas/fixtures/review-run.json`, 13.6): "Plan, build
and review" with `review` on, run to its pull request. A security lens finds a high-severity
problem on pass 1 and the gate sends the work back with no person; on pass 2 a medium finding and
a finding on a file the change did not touch reach the gate as comments, one is dismissed on
approval and the other becomes the pull request's review notes. The web reads "Sent back by
review", the comments on their lines and the review agents' inputs from these events.

Set `UPDATE_FIXTURES=1` to write the file again after a deliberate change to the events."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_engine.conformance import trace_mismatches
from agentic_engine.events import RunEvent
from agentic_engine.gate import GateDecision
from agentic_runtime.findings import Finding

from .test_ac2_review import SQL, STYLE, report, run_of

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "review-run.json"
RUN_ID = "00000000-0000-4000-8000-000000000136"
START = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
README = Finding(
    tool="agent", rule="docs", severity="low", category="correctness", path="README.md", line=1,
    message="The README does not mention the new validation.",
)  # fmt: skip


async def record() -> dict[str, Any]:
    run = run_of({"review_security": [report(SQL, STYLE, README), report(STYLE, README)]})
    paused = await run.start()
    assert paused.status == "waiting"
    shown = next(e for e in run.sink.events if e.type == "gate_waiting").payload["review"]
    dismissed = next(c["fingerprint"] for c in shown["comments"] if c["path"] == "README.md")
    done = await run.decide(
        GateDecision(decision="approve", decided_by="ada", dismissed=[dismissed])
    )
    assert done.status == "completed"
    assert trace_mismatches(run.spec.root, run.sink.events, run.spec.id) == []

    def at(seconds: float) -> str:
        return (START + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")

    def payload(e: RunEvent) -> dict[str, Any]:
        ttl = e.payload.get("ttl_s")
        if e.type == "gate_waiting" and isinstance(ttl, int):
            return {**e.payload, "expires_at": at(e.seq + ttl)}
        return dict(e.payload)

    events = [
        {
            "run_id": RUN_ID, "seq": e.seq, "type": e.type, "node_id": e.node_id,
            "payload": payload(e), "created_at": at(e.seq),
        }
        for e in run.sink.events
    ]  # fmt: skip
    spec = run.spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"spec": spec, "events": events}


async def test_the_web_fixture_is_the_engines_events() -> None:
    recorded = await record()
    text = json.dumps(recorded, indent=2) + "\n"
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    assert FIXTURE.exists(), "run with UPDATE_FIXTURES=1 to write the fixture"
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored == recorded, "the review run's events changed: UPDATE_FIXTURES=1"
