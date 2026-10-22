"""SQLAlchemy models. Alembic (in the api package) migrates `metadata`."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


metadata = Base.metadata

# The workspace every run belongs to until users and workspace membership exist.
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")

# A GitHub connection is an App installation and has no secret; every other provider has one.
CONNECTION_COLUMNS_CHECK = (
    "(provider = 'github' AND external_id IS NOT NULL) OR "
    "(provider <> 'github' AND secret_nonce IS NOT NULL AND secret_ciphertext IS NOT NULL "
    "AND key_hint IS NOT NULL)"
)


class Workspace(Base):
    """A tenant: it owns runs and connections.

    `wrapped_dek` is the workspace's data key, wrapped by the master key `key_id`. It is made when
    the first secret is stored, so a workspace with no secrets has none."""

    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Connection(Base):
    """A workspace's credentials for one provider, encrypted under the workspace's data key.

    `key_hint` (the last 4 characters) is the only part of the secret ever shown. A `github`
    connection holds no secret: `external_id` is its App installation and `account_login` the
    user or organisation it is installed on."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", name="uq_connections_workspace_id_provider"),
        CheckConstraint(CONNECTION_COLUMNS_CHECK, name="ck_connections_provider_columns"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    provider: Mapped[str] = mapped_column(String(32))
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_hint: Mapped[str | None] = mapped_column(String(8))
    external_id: Mapped[int | None] = mapped_column(BigInteger)
    account_login: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """A run's mutable summary and what it was started with. Its history lives in `run_events`.

    `status` is `queued` until a worker emits `run_started`, then `running`, then the status of
    the final run event (`completed`, `failed` or `cancelled`). A run paused at a gate is
    `waiting` (no worker holds it); a decision sets it back to `queued`, and `run_resumed` to
    `running`.

    The worker running a run holds its lease (`worker_id`, `lease_expires_at`) and renews it
    while alive. A `queued` or `running` run whose lease has expired was abandoned: another worker
    may claim it and resume it from its checkpoint. `attempt` counts claims (0 = never claimed)."""

    __tablename__ = "runs"
    __table_args__ = (
        Index(
            "ix_runs_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    status: Mapped[str] = mapped_column(String(32))
    spec: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    input: Mapped[str] = mapped_column(Text, server_default="")
    # The `RepoSource` the run works on, if any.
    repo: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunEventRow(Base):
    """One event of a run, append only. `(run_id, seq)` is unique and gives the order."""

    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_events_run_id_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"))
    seq: Mapped[int]
    type: Mapped[str] = mapped_column(String(64))
    node_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    """A human decision at a gate of a run, `approve` or `reject`; the paused run continues with
    it. One per gate and run: gates inside loops and maps will need an iteration key."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", name="uq_approvals_run_id_node_id"),
        CheckConstraint("decision IN ('approve', 'reject')", name="ck_approvals_decision"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"))
    node_id: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    # Who decided; unset until users and auth exist.
    decided_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
