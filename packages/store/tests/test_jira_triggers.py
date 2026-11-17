"""Jira trigger rules and what the receiver records (7.3)."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_store import (
    AuditEvent,
    JiraOrigin,
    JiraTriggerFields,
    JiraTriggerNotFoundError,
    Run,
    TriggerRunActiveError,
    Workspace,
    create_jira_trigger,
    create_run,
    delete_jira_trigger,
    get_jira_trigger,
    is_jira_own_move,
    jira_trigger_projects,
    list_jira_triggers,
    matching_jira_triggers,
    prune_jira_deliveries,
    record_jira_delivery,
    record_jira_own_move,
    record_jira_trigger_fire,
    trigger_matches,
    update_jira_trigger,
)

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
SPECS = Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures" / "specs" / "valid"
STATUS_RULE = JiraTriggerFields(
    cloud_id="cloud-acme", project_key="api", on="status", value="In Progress", template_id="t"
)
LABEL_RULE = JiraTriggerFields(
    cloud_id="cloud-acme", project_key="API", on="label", value="agent", workflow_id="wf"
)


def single_agent() -> WorkflowSpec:
    return parse_spec(json.loads((SPECS / "single-agent.json").read_text(encoding="utf-8")))


async def new_workspace(sessions: Sessions) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}"))
    return workspace_id


async def audit_actions(sessions: Sessions, workspace_id: UUID) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.id)
        )
        return list(rows)


def origin(trigger_id: UUID, key: str = "API-1", delivery_row: int | None = None) -> JiraOrigin:
    return JiraOrigin(
        trigger_id=trigger_id,
        delivery_row=delivery_row,
        delivery_id="d-1",
        issue={
            "cloud_id": "cloud-acme",
            "site": "acme.atlassian.net",
            "key": key,
            "url": f"https://acme.atlassian.net/browse/{key}",
        },
    )


# --- matching --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("on", "value", "status_to", "labels", "matches"),
    [
        ("status", "In Progress", "in progress", (), True),
        ("status", " In Progress ", "In Progress", (), True),
        ("status", "In Progress", "In Review", (), False),
        ("status", "In Progress", None, ("In Progress",), False),
        ("label", "agent", None, ("ready", "Agent"), True),
        ("label", "agent", "agent", (), False),
        ("label", "agent", None, ("agents",), False),
        ("other", "x", "x", ("x",), False),
    ],
)
def test_a_rule_matches_its_status_or_label_whatever_the_case(
    on: str, value: str, status_to: str | None, labels: tuple[str, ...], matches: bool
) -> None:
    assert trigger_matches(on, value, status_to=status_to, labels_added=labels) is matches


# --- rules -----------------------------------------------------------------------------------


async def test_rules_round_trip_and_are_audited(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    created = await create_jira_trigger(sessions, workspace_id, STATUS_RULE)
    assert created.fields.project_key == "API"  # keys are stored upper case
    assert created.last is None

    changed = await update_jira_trigger(
        sessions,
        workspace_id,
        created.id,
        replace(STATUS_RULE, value="Done", enabled=False),
    )
    assert (changed.fields.value, changed.fields.enabled) == ("Done", False)
    assert [t.id for t in await list_jira_triggers(sessions, workspace_id)] == [created.id]

    await delete_jira_trigger(sessions, workspace_id, created.id)
    assert await get_jira_trigger(sessions, workspace_id, created.id) is None
    assert await audit_actions(sessions, workspace_id) == [
        "jira.trigger_created",
        "jira.trigger_updated",
        "jira.trigger_deleted",
    ]


async def test_another_workspaces_rule_is_not_found(sessions: Sessions) -> None:
    mine = await new_workspace(sessions)
    theirs = await new_workspace(sessions)
    rule = await create_jira_trigger(sessions, theirs, STATUS_RULE)
    assert await get_jira_trigger(sessions, mine, rule.id) is None
    with pytest.raises(JiraTriggerNotFoundError):
        await update_jira_trigger(sessions, mine, rule.id, STATUS_RULE)
    with pytest.raises(JiraTriggerNotFoundError):
        await delete_jira_trigger(sessions, mine, rule.id)


async def test_matching_finds_enabled_rules_on_the_project(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    status = await create_jira_trigger(sessions, workspace_id, STATUS_RULE)
    label = await create_jira_trigger(sessions, workspace_id, LABEL_RULE)
    off = await create_jira_trigger(sessions, workspace_id, replace(LABEL_RULE, enabled=False))
    other_site = await create_jira_trigger(
        sessions, workspace_id, replace(LABEL_RULE, cloud_id="labs")
    )

    found = await matching_jira_triggers(
        sessions,
        workspace_id,
        "cloud-acme",
        "api",
        status_to="IN PROGRESS",
        labels_added=("agent",),
    )
    assert [t.id for t in found] == [status.id, label.id]
    assert off.id not in [t.id for t in found] and other_site.id not in [t.id for t in found]
    assert await jira_trigger_projects(sessions, workspace_id) == {
        "cloud-acme": ["API"],
        "labs": ["API"],
    }


# --- deliveries and fires --------------------------------------------------------------------


async def test_a_delivery_is_recorded_once_per_workspace(sessions: Sessions) -> None:
    first, second = await new_workspace(sessions), await new_workspace(sessions)
    row = await record_jira_delivery(sessions, first, "cloud-acme", "7001", "API-1")
    assert row is not None
    assert await record_jira_delivery(sessions, first, "cloud-acme", "7001", "API-1") is None
    # Another workspace's webhook matched the same delivery: it records its own.
    assert await record_jira_delivery(sessions, second, "cloud-acme", "7001", "API-1") is not None


async def test_concurrent_retries_record_one_delivery(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    rows = await asyncio.gather(
        *(
            record_jira_delivery(sessions, workspace_id, "cloud-acme", "7002", "API-1")
            for _ in "abcd"
        )
    )
    assert sum(row is not None for row in rows) == 1


async def test_a_started_run_records_its_rule_issue_and_fire(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    rule = await create_jira_trigger(sessions, workspace_id, STATUS_RULE)
    delivery = await record_jira_delivery(sessions, workspace_id, "cloud-acme", "7003", "API-1")

    run_id = await create_run(
        sessions,
        single_agent(),
        "API-1",
        workspace_id=workspace_id,
        jira_origin=origin(rule.id, delivery_row=delivery),
    )

    async with sessions() as session:
        run = await session.get(Run, run_id)
    assert run is not None
    assert (run.trigger, run.jira_trigger_id, run.input) == ("jira", rule.id, "API-1")
    assert run.jira_issue is not None and run.jira_issue["key"] == "API-1"
    found = await get_jira_trigger(sessions, workspace_id, rule.id)
    last = found.last if found else None
    assert last is not None and (last.outcome, last.run_id, last.issue_key) == (
        "started",
        run_id,
        "API-1",
    )
    assert await audit_actions(sessions, workspace_id) == [
        "jira.trigger_created",
        "run.created",
        "jira.trigger_fired",
    ]


async def test_a_rule_starts_one_run_per_issue_at_a_time(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    rule = await create_jira_trigger(sessions, workspace_id, STATUS_RULE)
    first = await create_run(
        sessions, single_agent(), "API-1", workspace_id=workspace_id, jira_origin=origin(rule.id)
    )
    with pytest.raises(TriggerRunActiveError) as active:
        await create_run(
            sessions,
            single_agent(),
            "API-1",
            workspace_id=workspace_id,
            jira_origin=origin(rule.id),
        )
    assert active.value.run_id == first
    # Another issue is not held up, and an ended run frees the issue.
    await create_run(
        sessions,
        single_agent(),
        "API-2",
        workspace_id=workspace_id,
        jira_origin=origin(rule.id, "API-2"),
    )
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == first).values(status="completed"))
    await create_run(
        sessions, single_agent(), "API-1", workspace_id=workspace_id, jira_origin=origin(rule.id)
    )


async def test_two_deliveries_at_once_start_one_run(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    rule = await create_jira_trigger(sessions, workspace_id, STATUS_RULE)

    async def start() -> UUID | None:
        try:
            return await create_run(
                sessions,
                single_agent(),
                "API-1",
                workspace_id=workspace_id,
                jira_origin=origin(rule.id),
            )
        except TriggerRunActiveError:
            return None

    started = await asyncio.gather(*(start() for _ in range(4)))
    assert sum(run is not None for run in started) == 1


async def test_a_refused_start_is_recorded_and_audited(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    rule = await create_jira_trigger(sessions, workspace_id, STATUS_RULE)
    await record_jira_trigger_fire(
        sessions, workspace_id, origin(rule.id), "start_failed", reason="GitHub is not connected"
    )
    found = await get_jira_trigger(sessions, workspace_id, rule.id)
    last = found.last if found else None
    assert last is not None and (last.outcome, last.reason) == (
        "start_failed",
        "GitHub is not connected",
    )
    assert (await audit_actions(sessions, workspace_id))[-1] == "jira.trigger_failed"


# --- own moves and pruning -------------------------------------------------------------------


async def test_a_runs_own_move_is_recognised_for_ten_minutes(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    await record_jira_own_move(sessions, workspace_id, "cloud-acme", "api-1", "Done", None)

    assert await is_jira_own_move(sessions, workspace_id, "cloud-acme", "API-1", "done")
    assert not await is_jira_own_move(sessions, workspace_id, "cloud-acme", "API-1", "To Do")
    assert not await is_jira_own_move(sessions, workspace_id, "cloud-acme", "API-2", "Done")
    later = datetime.now(UTC) + timedelta(minutes=11)
    assert not await is_jira_own_move(sessions, workspace_id, "cloud-acme", "API-1", "Done", later)


async def test_old_deliveries_are_pruned(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    await record_jira_delivery(sessions, workspace_id, "cloud-acme", "7009", "API-1")
    assert await prune_jira_deliveries(sessions) >= 0
    pruned = await prune_jira_deliveries(sessions, datetime.now(UTC) + timedelta(days=31))
    assert pruned >= 1
    # Once pruned, the same delivery id is new again.
    assert await record_jira_delivery(sessions, workspace_id, "cloud-acme", "7009", "API-1")
