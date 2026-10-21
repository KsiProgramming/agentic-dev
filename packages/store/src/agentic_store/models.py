"""SQLAlchemy models. Alembic (in the api package) migrates `metadata`."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


metadata = Base.metadata


class Run(Base):
    """A run's mutable summary. Its history lives in `run_events`."""

    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
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
