"""Gates in loops (7.8): an approval is per pass of its gate, `(run_id, node_id, iteration)`.

A gate that runs again (in a loop's body) pauses once per pass; its n-th `gate_waiting` event
is pass n, and the approval that answers it has `iteration` n. Existing rows are pass 1.

Revision ID: 0038_approval_iteration
Revises: 0037_run_spec_file
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_approval_iteration"
down_revision: str | None = "0037_run_spec_file"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "approvals", sa.Column("iteration", sa.Integer(), nullable=False, server_default="1")
    )
    op.drop_constraint("uq_approvals_run_id_node_id", "approvals", type_="unique")
    op.create_unique_constraint(
        "uq_approvals_run_id_node_id_iteration", "approvals", ["run_id", "node_id", "iteration"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_approvals_run_id_node_id_iteration", "approvals", type_="unique")
    op.execute(
        "DELETE FROM approvals a USING approvals b "
        "WHERE a.run_id = b.run_id AND a.node_id = b.node_id AND a.iteration < b.iteration"
    )
    op.create_unique_constraint("uq_approvals_run_id_node_id", "approvals", ["run_id", "node_id"])
    op.drop_column("approvals", "iteration")
