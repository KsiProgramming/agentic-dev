"""SQLAlchemy models. Alembic (in the api package) migrates `metadata`."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
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
    user or organisation it is installed on, `account_type` which of the two."""

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
    # `User` or `Organization` for GitHub; unset for connections made before it was recorded.
    account_type: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceModelPrice(Base):
    """A workspace's price for a model, overriding its list price. USD per million tokens."""

    __tablename__ = "workspace_model_prices"

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    input: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    output: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cache_write_5m: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cache_write_1h: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cache_read: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspacePolicy(Base):
    """A workspace's own run limits, each lower than the platform's; `NULL` keeps the platform's
    (`agentic_engine.policy.PLATFORM_POLICY`). `budget_usd` is the default budget of its runs;
    `NULL` is no budget."""

    __tablename__ = "workspace_policies"

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    agents_alive: Mapped[int | None] = mapped_column(Integer)
    agents_spawned: Mapped[int | None] = mapped_column(Integer)
    max_depth: Mapped[int | None] = mapped_column(Integer)
    loop_iterations: Mapped[int | None] = mapped_column(Integer)
    wall_time_s: Mapped[int | None] = mapped_column(Integer)
    approval_ttl_s: Mapped[int | None] = mapped_column(Integer)
    budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(16, 8))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Run(Base):
    """A run's mutable summary and what it was started with. Its history lives in `run_events`.

    `status` is `queued` until a worker emits `run_started`, then `running`, then the status of
    the final run event (`completed`, `failed` or `cancelled`). A run paused at a gate is
    `waiting` (no worker holds it); a decision sets it back to `queued`, and `run_resumed` to
    `running`.

    The worker running a run holds its lease (`worker_id`, `lease_expires_at`) and renews it
    while alive. A `queued` or `running` run whose lease has expired was abandoned: another worker
    may claim it and resume it from its checkpoint. `attempt` counts claims (0 = never claimed).

    The summary columns (`started_at`, `finished_at`, `pr_url`, `failure_reason`, `waiting_gate`,
    the time columns) are a projection of the run's events, written by `PostgresEventSink` with
    each event, so listing runs never scans the log. `template_id` and `repo_url` are set at
    creation, and `rerun_of` links a rerun to the run it repeats. `cancel_requested_at` is set
    when a user asks to cancel the run, or when its gate expires (`agentic_store.expiry`), with
    `cancel_reason`; the worker then ends it `cancelled`. `policy` holds the
    limits the run got when it was created (`agentic_engine.policy.Policy`); they never change,
    resumes included."""

    __tablename__ = "runs"
    __table_args__ = (
        Index(
            "ix_runs_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        # The expiry sweep (`agentic_store.expiry`).
        Index(
            "ix_runs_gate_expires_at",
            "gate_expires_at",
            postgresql_where=text("status = 'waiting'"),
        ),
        # Listing runs, newest first.
        Index(
            "ix_runs_workspace_created", "workspace_id", text("created_at DESC"), text("id DESC")
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    status: Mapped[str] = mapped_column(String(32))
    spec: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    policy: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    input: Mapped[str] = mapped_column(Text, server_default="")
    # The `RepoSource` the run works on, if any.
    repo: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, server_default="0")
    # The template the spec was built from, if any (e.g. `generate-docs`).
    template_id: Mapped[str | None] = mapped_column(String(128))
    # The template's options the run was started with (for "Edit and rerun" later).
    template_parameters: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    # The stored workflow version the spec was read from, if any (5.7).
    workflow_id: Mapped[str | None] = mapped_column(String(64))
    workflow_version: Mapped[int | None] = mapped_column(Integer)
    # A copy of each stored workflow version the spec calls (6.5), by `<id>@<version>`.
    subflows: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    repo_url: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pr_url: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    # `{node_id, title, expires_at}` of the gate the run is paused at.
    waiting_gate: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    # When that gate expires: the worker then cancels the run (`agentic_store.expiry`).
    gate_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rerun_of: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id"))
    # What started the run: `manual` (a person, from the web), `api` or `rerun`.
    trigger: Mapped[str] = mapped_column(String(32), server_default="api")
    # The branch the run works on: its repo's `ref`, else the default branch of a repo it created.
    branch: Mapped[str | None] = mapped_column(Text)
    # Time spent executing and paused at gates, in closed stretches (`sink.summary_values`):
    # `active_ms` is null until the run starts. The open stretch, if any, began at
    # `active_since` or `waiting_since`.
    active_ms: Mapped[int | None] = mapped_column(BigInteger)
    waiting_ms: Mapped[int] = mapped_column(BigInteger, server_default="0")
    active_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When a user asked to cancel the run (`agentic_store.cancel`), or its gate expired, and why:
    # the `reason` of its `run_cancelled` event, which also sets it.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    # Totals of the run's `usage` events.
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    estimated_usd: Mapped[Decimal] = mapped_column(Numeric(16, 8), server_default="0")
    # False once a usage event had no price: `estimated_usd` is then a lower bound.
    cost_complete: Mapped[bool] = mapped_column(Boolean, server_default=true())
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


class RunArtifact(Base):
    """One version of a run artifact (4.3), append only: `(run_id, name, version)` is its key, and
    versions are numbered per name from 1. The run's state names the versions it uses; the
    content is only here."""

    __tablename__ = "run_artifacts"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    # The writer's `output_schema`, if it had one.
    output_schema: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workflow(Base):
    """A stored workflow (5.1), keyed by its workspace and its spec's `id`. Its versions are in
    `workflow_versions`; `latest_version` is the one a change must start from."""

    __tablename__ = "workflows"

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    latest_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowVersion(Base):
    """One version of a workflow, append only (a trigger refuses `UPDATE` and `DELETE`): the spec,
    and the graph operations that made it from `base_version` (both unset for version 1). A
    restore (5.7) copies the spec of version `restored_from` and has no ops."""

    __tablename__ = "workflow_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "workflow_id"],
            ["workflows.workspace_id", "workflows.id"],
            name="fk_workflow_versions_workflow",
        ),
        CheckConstraint("version >= 1", name="ck_workflow_versions_version"),
    )

    workspace_id: Mapped[UUID] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    spec: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    base_version: Mapped[int | None] = mapped_column(Integer)
    ops: Mapped[list[JsonValue] | None] = mapped_column(JSONB)
    restored_from: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowPublication(Base):
    """A published version of a workflow (6.6), append only (a trigger refuses `UPDATE` and
    `DELETE`). A workflow with one is a composite: other workflows call its published versions,
    and its other versions are drafts."""

    __tablename__ = "workflow_publications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "workflow_id", "version"],
            [
                "workflow_versions.workspace_id",
                "workflow_versions.workflow_id",
                "workflow_versions.version",
            ],
            name="fk_workflow_publications_version",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
    # An approval's edits (`FileEdit`s as JSON), which the gate commits; NULL is none.
    edits: Mapped[list[JsonValue] | None] = mapped_column(JSONB)
    # A selection gate's approval: the keys of the items chosen (6.7); NULL for other gates.
    selection: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """One action in a workspace, append only (a trigger refuses `UPDATE` and `DELETE`). It is
    written in the transaction of the change it records (`agentic_store.audit`), so it exists if
    and only if the change was committed. `actor_type` is `user` or `system` (the worker);
    `actor_id` is unset until users and auth exist. `run_id` has no foreign key, so an entry
    outlives what it names."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'system')", name="ck_audit_events_actor_type"),
        # Listing a workspace's activity, newest first.
        Index("ix_audit_events_workspace_at", "workspace_id", text("at DESC"), text("id DESC")),
        Index("ix_audit_events_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(255))
    run_id: Mapped[UUID | None]
    node_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, server_default="{}")
