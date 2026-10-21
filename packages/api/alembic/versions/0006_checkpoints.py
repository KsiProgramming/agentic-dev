"""The LangGraph Postgres checkpointer's tables, where runs save their graph state per node.

The saver versions its own schema: `setup()` runs its `MIGRATIONS` in order and records each in
`checkpoint_migrations`. This revision does the same for the first `SAVER_MIGRATIONS` of them,
so workers never run DDL and the schema stays frozen here. A saver release that adds migrations
needs a new revision for the rest (`test_migrations` fails until then).

Revision ID: 0006_checkpoints
Revises: 0005_run_lease
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from langgraph.checkpoint.postgres.base import BasePostgresSaver

revision: str = "0006_checkpoints"
down_revision: str | None = "0005_run_lease"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAVER_MIGRATIONS = 10
"""How many of the saver's migrations this revision applies (v0..v9, saver 3.2)."""


def upgrade() -> None:
    # Some are `CREATE INDEX CONCURRENTLY`, which cannot run in a transaction (as in `setup()`).
    with op.get_context().autocommit_block():
        for v, migration in enumerate(BasePostgresSaver.MIGRATIONS[:SAVER_MIGRATIONS]):
            op.execute(migration)
            op.execute(sa.text("INSERT INTO checkpoint_migrations (v) VALUES (:v)").bindparams(v=v))


def downgrade() -> None:
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.drop_table(table)
