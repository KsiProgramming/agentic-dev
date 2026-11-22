"""Provider selection in the store (8.3): resolved and frozen when a run is created, kept by a rerun
from a step, and the workspace's own settings."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_store import (
    AuditEvent,
    ProviderGapError,
    ProviderSettings,
    Run,
    Workspace,
    create_rerun,
    create_run,
    get_provider_settings,
    get_run,
    put_provider_settings,
)
from agentic_store.providers import resolve_for_rerun

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
CONNECTION = (uuid4(), "ada")


def agent(node_id: str, **extra: Any) -> dict[str, Any]:
    return {"type": "agent", "id": node_id, "role": "Dev", "instructions": "Work.", **extra}


def spec_of(*steps: dict[str, Any], **extra: Any) -> WorkflowSpec:
    root = {"type": "sequence", "id": "seq", "steps": list(steps)}
    return parse_spec({"spec_version": "0", "id": "w", "name": "W", "root": root, **extra})


async def new_workspace(sessions: Sessions, default: str | None = None) -> UUID:
    workspace_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            Workspace(id=workspace_id, name=f"ws-{workspace_id.hex[:6]}", default_provider=default)
        )
    return workspace_id


async def connection_in(sessions: Sessions, workspace_id: UUID) -> tuple[UUID, str]:
    """A personal connection of the workspace, as `create_run` takes it."""
    from pydantic import SecretStr

    from agentic_secrets import KEY_BYTES, LocalKeyProvider
    from agentic_store import put_github_user_connection

    info = await put_github_user_connection(
        sessions,
        LocalKeyProvider(b"k" * KEY_BYTES),
        workspace_id,
        github_user_id=7,
        login="ada",
        scopes=None,
        secret=SecretStr('{"access_token":"gho_x","refresh_token":null}'),
    )
    return info.id, "ada"


async def stored(sessions: Sessions, run_id: UUID) -> Run:
    async with sessions() as session:
        return await session.get_one(Run, run_id)


async def test_a_run_with_nothing_set_resolves_to_claude(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)

    run_id = await create_run(sessions, spec_of(agent("a")), workspace_id=workspace_id)

    run = await stored(sessions, run_id)
    assert (run.provider, run.providers) == ("claude", ["claude"])
    assert run.provider_map == {
        "default": "claude",
        "nodes": {"a": {"provider": "claude", "model": None}},
        "fallback": [],
    }


async def test_the_workspace_default_is_used_when_the_run_is_started(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions, default="copilot")
    connection = await connection_in(sessions, workspace_id)

    run_id = await create_run(
        sessions,
        spec_of(agent("a", model="claude-opus-5-5")),
        workspace_id=workspace_id,
        copilot_connection=connection,
    )

    run = await stored(sessions, run_id)
    assert (run.provider, run.providers) == ("copilot", ["copilot"])
    assert run.provider_map is not None
    assert run.provider_map["nodes"] == {"a": {"provider": "copilot", "model": None}}


async def test_the_run_override_beats_the_workspace_but_not_a_node(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions, default="copilot")
    connection = await connection_in(sessions, workspace_id)

    run_id = await create_run(
        sessions,
        spec_of(agent("a"), agent("b", provider="copilot")),
        workspace_id=workspace_id,
        copilot_connection=connection,
        provider="claude",
    )

    run = await stored(sessions, run_id)
    assert (run.provider, run.providers) == ("claude", ["claude", "copilot"])


async def test_a_connection_alone_still_means_copilot_for_the_run(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    connection = await connection_in(sessions, workspace_id)

    run_id = await create_run(
        sessions, spec_of(agent("a")), workspace_id=workspace_id, copilot_connection=connection
    )

    assert (await stored(sessions, run_id)).providers == ["copilot"]


async def test_copilot_without_a_connection_is_refused_naming_the_nodes(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions, default="copilot")

    with pytest.raises(ProviderGapError) as refused:
        await create_run(sessions, spec_of(agent("a"), agent("b")), workspace_id=workspace_id)

    assert [(i.code, i.node_id) for i in refused.value.issues] == [
        ("copilot_connection_required", "a"),
        ("copilot_connection_required", "b"),
    ]
    async with sessions() as session:
        rows = await session.scalars(select(Run).where(Run.workspace_id == workspace_id))
        assert list(rows) == []


@pytest.mark.parametrize("trigger", ["jira", "github"])
async def test_a_triggered_run_stays_on_claude_and_is_never_refused(
    sessions: Sessions, trigger: str
) -> None:
    workspace_id = await new_workspace(sessions, default="copilot")

    run_id = await create_run(
        sessions,
        spec_of(agent("a"), agent("b", provider="copilot", model="gpt-5")),
        workspace_id=workspace_id,
        trigger=trigger,
    )

    run = await stored(sessions, run_id)
    assert (run.provider, run.providers) == ("claude", ["claude"])
    assert run.provider_map is not None
    assert run.provider_map["fallback"] == ["a", "b"]


async def test_a_budget_does_not_need_a_claude_price_for_a_copilot_model(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    connection = await connection_in(sessions, workspace_id)

    run_id = await create_run(
        sessions,
        spec_of(agent("a", provider="copilot", model="gpt-5")),
        workspace_id=workspace_id,
        copilot_connection=connection,
        budget_usd=Decimal("1"),
    )

    assert (await stored(sessions, run_id)).providers == ["copilot"]


async def test_the_stored_run_carries_its_frozen_resolution(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    run_id = await create_run(sessions, spec_of(agent("a")), workspace_id=workspace_id)
    await put_provider_settings(
        sessions, workspace_id, ProviderSettings(default_provider="copilot")
    )

    run = await get_run(sessions, run_id)

    assert run is not None
    assert (run.provider, run.providers) == ("claude", ("claude",))
    assert run.resolved is not None
    assert run.resolved.of("a") is not None
    assert run.resolved.nodes["a"].provider == "claude"  # the default changed after: not moved


async def test_a_rerun_from_the_beginning_resolves_again(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    original = await create_run(sessions, spec_of(agent("a")), workspace_id=workspace_id)
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == original).values(status="completed"))
    await put_provider_settings(
        sessions, workspace_id, ProviderSettings(default_provider="copilot")
    )

    with pytest.raises(ProviderGapError):  # Copilot now, and the person has no connection
        await create_rerun(sessions, original)

    await put_provider_settings(sessions, workspace_id, ProviderSettings(default_provider="claude"))
    again = await create_rerun(sessions, original)
    assert (await stored(sessions, again)).providers == ["claude"]


async def test_a_rerun_from_a_step_keeps_what_the_original_stored(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions, default="copilot")
    connection = await connection_in(sessions, workspace_id)
    original_id = await create_run(
        sessions,
        spec_of(agent("a"), agent("b")),
        workspace_id=workspace_id,
        copilot_connection=connection,
    )
    await put_provider_settings(sessions, workspace_id, ProviderSettings(default_provider="claude"))
    original = await stored(sessions, original_id)
    spec = spec_of(agent("a"), agent("b"))

    async with sessions() as session:
        kept = await resolve_for_rerun(session, original, spec, from_step=True, follow_up=False)
        fresh = await resolve_for_rerun(session, original, spec, from_step=False, follow_up=False)
        followed = await resolve_for_rerun(session, original, spec, from_step=True, follow_up=True)

    assert kept.providers == ["copilot"]
    assert fresh.providers == ["copilot"]  # the person's own Copilot choice goes on
    assert (followed.providers, followed.fallback) == (["claude"], [])  # a trigger: Claude


async def test_a_run_from_before_8_3_has_no_resolution_and_resolves_from_its_provider(
    sessions: Sessions,
) -> None:
    workspace_id = await new_workspace(sessions)
    run_id = await create_run(sessions, spec_of(agent("a")), workspace_id=workspace_id)
    async with sessions.begin() as session:
        await session.execute(update(Run).where(Run.id == run_id).values(provider_map=None))

    run = await get_run(sessions, run_id)

    assert run is not None
    assert (run.provider, run.resolved) == ("claude", None)


async def test_settings_round_trip_with_an_audit_entry(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    assert await get_provider_settings(sessions, workspace_id) == ProviderSettings()

    saved = await put_provider_settings(
        sessions,
        workspace_id,
        ProviderSettings("copilot", "gpt-5", Decimal("0.02")),
    )

    assert await get_provider_settings(sessions, workspace_id) == saved
    assert saved.credit_usd == Decimal("0.02")
    async with sessions() as session:
        rows = list(
            await session.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id))
        )
    [entry] = [r for r in rows if r.action == "workspace.settings_changed"]
    assert entry.details["changed"] == ["default_provider", "copilot_model", "copilot_credit_usd"]
    assert "gho" not in str(entry.details)


async def test_saving_the_same_settings_again_is_not_audited(sessions: Sessions) -> None:
    workspace_id = await new_workspace(sessions)
    same = ProviderSettings("copilot")
    await put_provider_settings(sessions, workspace_id, same)
    await put_provider_settings(sessions, workspace_id, same)

    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.action == "workspace.settings_changed",
                )
            )
        )
    assert len(rows) == 1
