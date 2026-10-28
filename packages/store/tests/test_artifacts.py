"""Run artifacts in Postgres (4.3): every version is kept, and a run reads its own."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.spec import parse_spec
from agentic_runtime import Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_store import (
    PostgresArtifactStore,
    PostgresEventSink,
    create_run,
    get_run_artifact,
    list_run_artifacts,
    pending_gate,
)

pytestmark = pytest.mark.integration

SPEC = parse_spec(
    {
        "spec_version": "0",
        "id": "notes",
        "name": "Notes",
        "root": {"type": "agent", "id": "a", "role": "R", "instructions": "Go."},
    }
)
FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "fixtures"
    / "specs"
    / "valid"
    / "artifacts-findings.json"
)


async def test_versions_are_numbered_per_name_and_all_kept(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, SPEC)
    store = PostgresArtifactStore(sessions, run_id)

    first = await store.put("notes.md", "a", "one")
    second = await store.put("notes.md", "b", "two")
    other = await store.put("f.json", "a", "{}", {"type": "object"})

    assert (first.version, second.version, other.version) == (1, 2, 1)
    latest = await store.get("notes.md")
    assert latest is not None and (latest.content, latest.node_id) == ("two", "b")
    old = await store.get("notes.md", 1)
    assert old is not None and old.content == "one"
    assert await store.get("notes.md", 3) is None
    assert await store.get("missing.txt") is None
    stored = await store.get("f.json")
    assert stored is not None and stored.output_schema == {"type": "object"}
    assert [(r.name, r.version) for r in await store.latest()] == [
        ("f.json", 1),
        ("notes.md", 2),
    ]
    assert await store.total_bytes() == len("one") + len("two") + len("{}")


async def test_the_api_lists_the_latest_version_with_its_count(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await create_run(sessions, SPEC)
    store = PostgresArtifactStore(sessions, run_id)
    await store.put("notes.md", "a", "one")
    await store.put("notes.md", "a", "two")
    # Another run's artifacts are not this run's.
    await PostgresArtifactStore(sessions, await create_run(sessions, SPEC)).put("x.txt", "a", "x")

    [listed] = await list_run_artifacts(sessions, run_id)
    found = await get_run_artifact(sessions, run_id, "notes.md", 1)

    assert (listed.name, listed.version, listed.versions, listed.media_type) == (
        "notes.md",
        2,
        2,
        "text/markdown",
    )
    assert found is not None
    artifact, shown = found
    assert (artifact.content, shown.version, shown.versions) == ("one", 1, 2)
    assert await get_run_artifact(sessions, run_id, "x.txt") is None
    assert await list_run_artifacts(sessions, uuid4()) == []


async def test_a_paused_run_shows_its_artifacts_at_the_gate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    spec = parse_spec(json.loads(FIXTURE.read_text(encoding="utf-8")))
    findings = json.dumps({"findings": []})
    run_id = await create_run(sessions, spec, findings)
    store = PostgresArtifactStore(sessions, run_id)

    result = await run_workflow(
        spec,
        FakeRuntime({"summary": [Message(text="ok"), ECHO_USAGE]}),
        findings,
        run_id=run_id,
        sink=PostgresEventSink(sessions),
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
        artifacts=store,
    )
    gate = await pending_gate(sessions, run_id)

    assert result.status == "waiting"
    [shown] = gate.run_artifacts
    assert (shown.name, shown.version, shown.node_id) == ("findings.json", 1, "scan")
    [listed] = await list_run_artifacts(sessions, run_id)
    assert listed.name == "findings.json"
