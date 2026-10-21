"""SQLAlchemy models. Alembic (in the api package) migrates `metadata`."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
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


class Run(Base):
    """A run's mutable summary and what it was started with. Its history lives in `run_events`.

    `status` is `queued` until a worker emits `run_started`, then `running`, then the status of
    the final run event (`completed`, `failed` or `cancelled`).

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
