"""The audit-and-fix run the web's console and review tests fold
(`schemas/fixtures/audit-fix-run.json`, 6.7): an audit with `fix` on that pauses at its selection
gate, fixes two of three findings with two tasks, pauses at the PR gate and opens the pull
request. `waiting` is how many events the run had at its first pause, and `artifacts` the
content of `findings.json`, which the checklist reads its items from. The web reads the engine's
real event shapes, so a change on either side fails a test.

Set `UPDATE_FIXTURES=1` to write the file again after a deliberate change to the events."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_engine.events import RunEvent
from agentic_engine.gate import GateDecision

from .test_audit_fix import AuditRun

FIXTURE = Path(__file__).resolve().parents[3] / "schemas" / "fixtures" / "audit-fix-run.json"
RUN_ID = "00000000-0000-4000-8000-000000000067"
START = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


async def record() -> dict[str, Any]:
    run = AuditRun()
    await run.start()
    waiting = len(run.sink.events)
    await run.decide(GateDecision(decision="approve", selection=["b", "a"]))
    result = await run.decide(GateDecision(decision="approve"))
    assert result.status == "completed"
    findings = await run.artifacts.get("findings.json")
    assert findings is not None

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
    return {
        "spec": run.spec.model_dump(mode="json", exclude_none=True),
        "waiting": waiting,
        "artifacts": {"findings.json": json.loads(findings.content)},
        "events": events,
    }


async def test_the_web_fixture_is_the_engines_events() -> None:
    recorded = await record()
    text = json.dumps(recorded, indent=2) + "\n"
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    assert FIXTURE.exists(), "run with UPDATE_FIXTURES=1 to write the fixture"
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert stored == recorded, "the audit-and-fix run's events changed: run UPDATE_FIXTURES=1"
