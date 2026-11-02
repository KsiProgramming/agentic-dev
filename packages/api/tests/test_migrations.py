import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

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

    assert version == "0025_workflow_restore"
    assert {
        "runs",
        "run_events",
        "workspaces",
        "connections",
        "approvals",
        "workspace_model_prices",
        "workspace_policies",
        "audit_events",
        "run_artifacts",
        "workflows",
        "workflow_versions",
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


async def test_the_workflow_version_revision_downgrades_and_upgrades(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")

    await asyncio.to_thread(command.downgrade, config, "0024_workflows")
    assert not {"workflow_id", "workflow_version"} & await run_columns(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"workflow_id", "workflow_version"} <= await run_columns(postgres_url)


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


async def test_workflow_versions_are_append_only(postgres_url: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO workflows (workspace_id, id, latest_version) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'append-only', 1)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO workflow_versions (workspace_id, workflow_id, version, spec) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 'append-only', 1, '{}')"
            )
        )
    for statement in (
        "UPDATE workflow_versions SET spec = '{\"x\": 1}'",
        "DELETE FROM workflow_versions",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(text(statement))
    await engine.dispose()

    await asyncio.to_thread(command.downgrade, config, "0023_run_artifacts")
    assert not {"workflows", "workflow_versions"} & await table_names(postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"workflows", "workflow_versions"} <= await table_names(postgres_url)


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


async def test_the_approval_expiry_revision_gives_waiting_gates_72_hours(
    postgres_url: str,
) -> None:
    """A gate that paused before phase 11.3 expires 72 h after it started waiting, so one paused
    4 days ago is past its time and goes on the first sweep."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0020_active_waiting_time")
    assert {"gate_expires_at", "cancel_reason"}.isdisjoint(await run_columns(postgres_url))
    assert "approval_ttl_s" not in await policy_columns(postgres_url)

    engine = create_async_engine(postgres_url)
    insert = (
        "INSERT INTO runs (id, workspace_id, status, spec, policy, waiting_gate, waiting_since, "
        "cancel_requested_at) VALUES (gen_random_uuid(), '00000000-0000-0000-0000-000000000001', "
        ":status, '{}', '{}', CAST(:gate AS jsonb), :since, :cancel) RETURNING id"
    )
    gate = '{"node_id": "approve", "title": "Ship it?"}'
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        stale, fresh, cancelled = [
            (
                await conn.execute(
                    text(insert),
                    {"status": status, "gate": gate_json, "since": since, "cancel": cancel},
                )
            ).scalar_one()
            for status, gate_json, since, cancel in (
                ("waiting", gate, now - timedelta(days=4), None),
                ("waiting", gate, now - timedelta(hours=1), None),
                ("cancelled", None, None, now),
            )
        ]
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        rows = {
            row.id: row
            for row in await conn.execute(
                text(
                    "SELECT id, gate_expires_at, waiting_gate, cancel_reason FROM runs "
                    "WHERE id IN (:a, :b, :c)"
                ),
                {"a": stale, "b": fresh, "c": cancelled},
            )
        }
    # Gone again, so no later test's worker expires them (their specs cannot run).
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM runs WHERE id IN (:a, :b, :c)"),
            {"a": stale, "b": fresh, "c": cancelled},
        )
    await engine.dispose()

    assert rows[stale].gate_expires_at < now < rows[fresh].gate_expires_at
    assert rows[fresh].gate_expires_at - (now - timedelta(hours=1)) == pytest.approx(
        timedelta(hours=72), abs=timedelta(seconds=1)
    )
    expires_at = datetime.fromisoformat(rows[fresh].waiting_gate["expires_at"])
    assert expires_at == rows[fresh].gate_expires_at
    assert rows[cancelled].cancel_reason == "cancelled by user"
    assert "approval_ttl_s" in await policy_columns(postgres_url)


async def test_the_runs_list_revision_backfills_trigger_and_branch(postgres_url: str) -> None:
    """Runs from before phase 11.4: one from the API on a ref, a template run (only the web sends
    templates) on the default branch, and a rerun of it on a repo it created."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", postgres_url)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "0021_approval_expiry")
    assert {"trigger", "branch"}.isdisjoint(await run_columns(postgres_url))

    engine = create_async_engine(postgres_url)
    insert = (
        "INSERT INTO runs (id, workspace_id, status, spec, policy, repo, template_id, rerun_of) "
        "VALUES (gen_random_uuid(), '00000000-0000-0000-0000-000000000001', 'completed', '{}', "
        "'{}', CAST(:repo AS jsonb), :template, :rerun_of) RETURNING id"
    )
    on_ref = '{"url": "https://github.com/acme/docs", "ref": "dev"}'
    on_default = '{"url": "https://github.com/acme/docs"}'
    async with engine.begin() as conn:

        async def add(repo: str | None, template: str | None, rerun_of: UUID | None) -> UUID:
            params = {"repo": repo, "template": template, "rerun_of": rerun_of}
            return (await conn.execute(text(insert), params)).scalar_one()

        api_run = await add(on_ref, None, None)
        manual = await add(on_default, "generate-docs", None)
        rerun = await add(None, "generate-docs", manual)
        await conn.execute(
            text(
                "INSERT INTO run_events (run_id, seq, type, payload, created_at) VALUES "
                "(:id, 1, 'repo_created', CAST(:payload AS jsonb), now())"
            ),
            {"id": rerun, "payload": '{"default_branch": "main"}'},
        )
    await asyncio.to_thread(command.upgrade, config, "head")
    async with engine.connect() as conn:
        rows = {
            row.id: (row.trigger, row.branch)
            for row in await conn.execute(
                text("SELECT id, trigger, branch FROM runs WHERE id IN (:a, :b, :c)"),
                {"a": api_run, "b": manual, "c": rerun},
            )
        }
    # Gone again, so no later test lists them.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM run_events WHERE run_id = :c"), {"c": rerun})
        await conn.execute(text("DELETE FROM runs WHERE id = :c"), {"c": rerun})
        await conn.execute(
            text("DELETE FROM runs WHERE id IN (:a, :b)"), {"a": api_run, "b": manual}
        )
    await engine.dispose()

    assert rows == {api_run: ("api", "dev"), manual: ("manual", None), rerun: ("rerun", "main")}
