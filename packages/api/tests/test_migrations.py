import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
CHECKPOINT_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


async def test_upgrade_head_creates_run_tables(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)

    # env.py calls asyncio.run, so the command must run outside this event loop.
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        tables = (
            await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
            )
        ).scalars()
        table_names = list(tables)
    await engine.dispose()

    assert version == "0020_active_waiting_time"
    assert {
        "runs",
        "run_events",
        "workspaces",
        "connections",
        "approvals",
        "workspace_model_prices",
        "workspace_policies",
        "audit_events",
    } | CHECKPOINT_TABLES <= set(table_names)
    # The migrations match the `agentic_store` models.
    await asyncio.to_thread(command.check, config)


async def test_the_run_repo_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.downgrade, config, "0003_run_spec")
    assert "repo" not in await run_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "repo" in await run_columns(postgres_url)


async def run_columns(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'runs'")
        )
        columns = set(rows.scalars())
    await engine.dispose()
    return columns


async def test_checkpoint_tables_match_the_installed_saver(postgres_url: str) -> None:
    """Revision 0006 applies every migration the installed saver has, as its `setup()` would.
    If this fails after upgrading `langgraph-checkpoint-postgres`, add a revision for the rest."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        applied = list(
            (await conn.execute(text("SELECT v FROM checkpoint_migrations ORDER BY v"))).scalars()
        )
    await engine.dispose()

    assert applied == list(range(len(BasePostgresSaver.MIGRATIONS)))


async def test_the_lease_and_checkpoint_revisions_downgrade_and_upgrade(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.downgrade, config, "0004_run_repo")
    assert not {"worker_id", "lease_expires_at", "attempt"} & await run_columns(postgres_url)
    assert not CHECKPOINT_TABLES & await table_names(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"worker_id", "lease_expires_at", "attempt"} <= await run_columns(postgres_url)
    assert await table_names(postgres_url) >= CHECKPOINT_TABLES


async def table_names(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = set(rows.scalars())
    await engine.dispose()
    return names


async def test_the_workspaces_revision_moves_existing_runs_to_the_default_workspace(
    postgres_url: str,
) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0006_checkpoints")
    assert not {"workspaces", "connections"} & await table_names(postgres_url)

    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        run_id = (
            await conn.execute(
                text(
                    "INSERT INTO runs (id, status, spec) "
                    "VALUES (gen_random_uuid(), 'completed', '{}') RETURNING id"
                )
            )
        ).scalar_one()
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        workspace_id = (
            await conn.execute(text("SELECT workspace_id FROM runs WHERE id = :id"), {"id": run_id})
        ).scalar_one()
    await engine.dispose()

    assert str(workspace_id) == "00000000-0000-0000-0000-000000000001"


async def connection_columns(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'connections'"
            )
        )
        columns = set(rows.scalars())
    await engine.dispose()
    return columns


async def test_the_github_connections_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO connections (id, workspace_id, provider, external_id, account_login) "
                "VALUES (gen_random_uuid(), '00000000-0000-0000-0000-000000000001', 'github', "
                "42, 'acme')"
            )
        )
    await engine.dispose()

    # The downgrade drops GitHub rows, which the restored NOT NULL secret columns cannot hold.
    await asyncio.to_thread(command.downgrade, config, "0007_workspaces_connections")
    assert not {"external_id", "account_login"} & await connection_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"external_id", "account_login"} <= await connection_columns(postgres_url)


async def test_the_policy_revision_gives_existing_runs_the_platform_policy(
    postgres_url: str,
) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0015_workspace_model_prices")
    assert "workspace_policies" not in await table_names(postgres_url)

    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        run_id = (
            await conn.execute(
                text(
                    "INSERT INTO runs (id, workspace_id, status, spec) VALUES (gen_random_uuid(), "
                    "'00000000-0000-0000-0000-000000000001', 'completed', '{}') RETURNING id"
                )
            )
        ).scalar_one()
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        policy = (
            await conn.execute(text("SELECT policy FROM runs WHERE id = :id"), {"id": run_id})
        ).scalar_one()
    await engine.dispose()

    assert policy == {
        "agents_alive": 8,
        "agents_spawned": 40,
        "max_depth": 2,
        "loop_iterations": 5,
        "wall_time_s": 7200,
    }
    assert "workspace_policies" in await table_names(postgres_url)


async def policy_columns(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'workspace_policies'"
            )
        )
        columns = set(rows.scalars())
    await engine.dispose()
    return columns


async def test_the_budget_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "budget_usd" in await policy_columns(postgres_url)

    await asyncio.to_thread(command.downgrade, config, "0016_policy_limits")
    assert "budget_usd" not in await policy_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "budget_usd" in await policy_columns(postgres_url)


async def approval_columns(postgres_url: str) -> set[str]:
    engine = create_async_engine(postgres_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'approvals'"
            )
        )
        columns = set(rows.scalars())
    await engine.dispose()
    return columns


async def test_the_approval_edits_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "edits" in await approval_columns(postgres_url)

    await asyncio.to_thread(command.downgrade, config, "0017_optional_budget")
    assert "edits" not in await approval_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "edits" in await approval_columns(postgres_url)


async def test_the_audit_revision_backfills_runs_and_approvals(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0018_approval_edits")
    assert "audit_events" not in await table_names(postgres_url)

    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        insert_run = (
            "INSERT INTO runs (id, workspace_id, status, spec, created_at, finished_at, "
            "cancel_requested_at, rerun_of, template_id, policy) VALUES (gen_random_uuid(), "
            "'00000000-0000-0000-0000-000000000001', :status, '{}', :created, :finished, "
            ":cancel, :rerun_of, 'audit-backfill', "
            '\'{"budget_usd": "5"}\'::jsonb) RETURNING id'
        )
        first = (
            await conn.execute(
                text(insert_run),
                {
                    "status": "completed",
                    "created": datetime.fromisoformat("2026-10-01T10:00:00+00:00"),
                    "finished": datetime.fromisoformat("2026-10-01T10:05:00+00:00"),
                    "cancel": None,
                    "rerun_of": None,
                },
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO approvals (run_id, node_id, decision, comment, edits, created_at) "
                "VALUES (:run, 'approve', 'approve', 'ok', "
                '\'[{"node_id": "w", "path": "a.md", "content": "x"}]\'::jsonb, '
                "'2026-10-01T10:02:00Z')"
            ),
            {"run": first},
        )
        # An approval stored with no edits holds JSON `null`.
        rejected = (
            await conn.execute(
                text(insert_run),
                {
                    "status": "cancelled",
                    "created": datetime.fromisoformat("2026-10-01T09:00:00+00:00"),
                    "finished": datetime.fromisoformat("2026-10-01T09:05:00+00:00"),
                    "cancel": None,
                    "rerun_of": None,
                },
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO approvals (run_id, node_id, decision, edits, created_at) "
                "VALUES (:run, 'approve', 'reject', 'null'::jsonb, '2026-10-01T09:02:00Z')"
            ),
            {"run": rejected},
        )
        second = (
            await conn.execute(
                text(insert_run),
                {
                    "status": "cancelled",
                    "created": datetime.fromisoformat("2026-10-01T11:00:00+00:00"),
                    "finished": datetime.fromisoformat("2026-10-01T11:01:00+00:00"),
                    "cancel": datetime.fromisoformat("2026-10-01T11:00:30+00:00"),
                    "rerun_of": first,
                },
            )
        ).scalar_one()
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT action, actor_type, run_id, node_id, details FROM audit_events "
                    "WHERE run_id IN (:a, :b) ORDER BY id"
                ),
                {"a": first, "b": second},
            )
        ).all()
    await engine.dispose()

    assert [(r.action, r.actor_type, r.run_id) for r in rows] == [
        ("run.created", "user", first),
        ("gate.approved", "user", first),
        ("run.ended", "system", first),
        ("run.rerun", "user", second),
        ("run.cancel_requested", "user", second),
        ("run.ended", "system", second),
    ]
    assert rows[0].details == {"template_id": "audit-backfill", "repo_url": None, "budget_usd": "5"}
    assert rows[1].node_id == "approve"
    assert rows[1].details == {"comment": "ok", "edited_files": 1, "edited_paths": ["a.md"]}
    assert rows[3].details["rerun_of"] == str(first)
    assert rows[5].details["status"] == "cancelled"
    async with engine.connect() as conn:
        decision = (
            await conn.execute(
                text(
                    "SELECT action, details FROM audit_events "
                    "WHERE run_id = :run AND action LIKE 'gate.%'"
                ),
                {"run": rejected},
            )
        ).one()
    await engine.dispose()
    assert decision.action == "gate.rejected"
    assert decision.details == {"comment": None, "edited_files": 0, "edited_paths": []}


async def test_audit_events_are_append_only(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (workspace_id, action, actor_type) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'policy.updated', 'user')"
            )
        )
    for statement in (
        "UPDATE audit_events SET action = 'x'",
        "DELETE FROM audit_events",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(text(statement))
    await engine.dispose()

    await asyncio.to_thread(command.downgrade, config, "0018_approval_edits")
    assert "audit_events" not in await table_names(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert "audit_events" in await table_names(postgres_url)


async def test_the_time_revision_fills_live_runs_from_their_events(postgres_url: str) -> None:
    """A run waiting at a gate when it ships gets its active time; one that had ended keeps
    none."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0019_audit_events")

    engine = create_async_engine(postgres_url)
    runs: dict[str, object] = {}
    async with engine.begin() as conn:
        for status, events in (
            (
                "waiting",
                (("run_started", 0), ("node_started", 10), ("gate_waiting", 60)),
            ),
            (
                "completed",
                (("run_started", 0), ("run_completed", 60)),
            ),
        ):
            runs[status] = (
                await conn.execute(
                    text(
                        "INSERT INTO runs (id, workspace_id, status, spec, policy) VALUES "
                        "(gen_random_uuid(), '00000000-0000-0000-0000-000000000001', :status, "
                        "'{}', '{}') RETURNING id"
                    ),
                    {"status": status},
                )
            ).scalar_one()
            for seq, (type, seconds) in enumerate(events, 1):
                await conn.execute(
                    text(
                        "INSERT INTO run_events (run_id, seq, type, payload, created_at) VALUES "
                        "(:run, :seq, :type, '{}', "
                        "timestamptz '2026-10-27 09:00:00+00' + make_interval(secs => :s))"
                    ),
                    {"run": runs[status], "seq": seq, "type": type, "s": seconds},
                )
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        rows = {
            status: (
                await conn.execute(
                    text(
                        "SELECT active_ms, waiting_ms, active_since, waiting_since FROM runs "
                        "WHERE id = :id"
                    ),
                    {"id": run_id},
                )
            ).one()
            for status, run_id in runs.items()
        }
    await engine.dispose()

    waiting = rows["waiting"]
    assert (waiting.active_ms, waiting.waiting_ms, waiting.active_since) == (60_000, 0, None)
    assert waiting.waiting_since == datetime.fromisoformat("2026-10-27T09:01:00+00:00")
    assert tuple(rows["completed"]) == (None, 0, None, None)

    await asyncio.to_thread(command.downgrade, config, "0019_audit_events")
    assert "active_ms" not in await run_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
