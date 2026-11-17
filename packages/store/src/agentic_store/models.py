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

# A GitHub connection is an App installation and has no secret; a Jira connection (7.1) is an
# OAuth grant, a secret with no hint (its tokens rotate); every other provider has a secret and
# its hint.
CONNECTION_COLUMNS_CHECK = (
    "(provider = 'github' AND external_id IS NOT NULL) OR "
    "(provider = 'jira' AND secret_nonce IS NOT NULL AND secret_ciphertext IS NOT NULL) OR "
    "(provider NOT IN ('github', 'jira') AND secret_nonce IS NOT NULL "
    "AND secret_ciphertext IS NOT NULL AND key_hint IS NOT NULL)"
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
    # Jira (7.1): the scopes the grant holds, and why the connection cannot be used (a fixed
    # reason: `invalid_grant`, `scopes`) until its account connects again.
    scopes: Mapped[list[str] | None] = mapped_column(JSONB)
    needs_attention: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JiraSite(Base):
    """A Jira Cloud site a workspace's Jira connection reaches (7.1). `enabled` is the
    workspace's choice; nothing on a site is usable until projects are picked (`JiraProject`)."""

    __tablename__ = "jira_sites"
    __table_args__ = (
        UniqueConstraint("connection_id", "cloud_id", name="uq_jira_sites_connection_id_cloud_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    cloud_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())


class JiraProject(Base):
    """A project of a site the workspace may use (7.1): the platform's own allowlist, since
    Atlassian's consent is per site. `key` and `name` are as they were when picked."""

    __tablename__ = "jira_projects"
    __table_args__ = (
        UniqueConstraint("site_id", "project_id", name="uq_jira_projects_site_id_project_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    site_id: Mapped[UUID] = mapped_column(ForeignKey("jira_sites.id", ondelete="CASCADE"))
    project_id: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))


class JiraFieldMapping(Base):
    """Which of a picked project's Jira fields holds a role (7.4): `acceptance_criteria` or
    `story_points`. Kept with its picked project, and removed with it (unpicked, its site no
    longer reached, or the connection removed). `field_name` is as it was when mapped."""

    __tablename__ = "jira_field_mappings"
    __table_args__ = (
        UniqueConstraint("project_id", "role", name="uq_jira_field_mappings_project_id_role"),
        CheckConstraint(
            "role IN ('acceptance_criteria', 'story_points')", name="ck_jira_field_mappings_role"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("jira_projects.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    field_id: Mapped[str] = mapped_column(String(255))
    field_name: Mapped[str] = mapped_column(String(255))


class JiraTrigger(Base):
    """A rule that starts a run when an issue of a picked project moves to a status (`on =
    'status'`) or gets a label (`on = 'label'`) (7.3). What runs is a template or a stored
    workflow (its latest version when `workflow_version` is null), on `repo_url` at `ref`; its
    input is the issue key."""

    __tablename__ = "jira_triggers"
    __table_args__ = (
        CheckConstraint("\"on\" IN ('status', 'label')", name="ck_jira_triggers_on"),
        CheckConstraint(
            "(template_id IS NULL) <> (workflow_id IS NULL)", name="ck_jira_triggers_target"
        ),
        Index("ix_jira_triggers_workspace_site_project", "workspace_id", "cloud_id", "project_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    cloud_id: Mapped[str] = mapped_column(String(64))
    project_key: Mapped[str] = mapped_column(String(32))
    on: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(255))
    template_id: Mapped[str | None] = mapped_column(String(128))
    workflow_id: Mapped[str | None] = mapped_column(String(64))
    workflow_version: Mapped[int | None] = mapped_column(Integer)
    repo_url: Mapped[str | None] = mapped_column(Text)
    ref: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JiraWebhook(Base):
    """The webhook a workspace holds on a Jira site for its triggers (7.3): Jira's id for it,
    the URL and projects it was registered with, when it expires, and the last failure to
    register or renew it (`error`, a fixed kind), cleared by the next success."""

    __tablename__ = "jira_webhooks"
    __table_args__ = (
        UniqueConstraint("workspace_id", "cloud_id", name="uq_jira_webhooks_workspace_id_cloud_id"),
        Index("ix_jira_webhooks_cloud_id_webhook_id", "cloud_id", "webhook_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    cloud_id: Mapped[str] = mapped_column(String(64))
    webhook_id: Mapped[int | None] = mapped_column(BigInteger)
    url: Mapped[str | None] = mapped_column(Text)
    projects: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(64))
    error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JiraDelivery(Base):
    """One webhook delivery a workspace received (7.3), kept 30 days. `(workspace_id, cloud_id,
    delivery_id)` is unique, so a retry of the same delivery is dropped. `outcome` is what the
    delivery came to before rules were tried (`project_not_allowed`, `own_change`, `no_match`)
    or `matched`; what each matching rule did is a `JiraTriggerFire`."""

    __tablename__ = "jira_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "cloud_id", "delivery_id", name="uq_jira_deliveries_delivery"
        ),
        Index("ix_jira_deliveries_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    cloud_id: Mapped[str] = mapped_column(String(64))
    delivery_id: Mapped[str] = mapped_column(String(64))
    issue_key: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32), server_default="received")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JiraTriggerFire(Base):
    """What a rule did with a delivery that matched it (7.3): `started` (with the run),
    `already_running` (with the run still going) or `start_failed` (with the reason)."""

    __tablename__ = "jira_trigger_fires"
    __table_args__ = (Index("ix_jira_trigger_fires_trigger_at", "trigger_id", text("at DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    trigger_id: Mapped[UUID] = mapped_column(ForeignKey("jira_triggers.id", ondelete="CASCADE"))
    delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("jira_deliveries.id", ondelete="SET NULL")
    )
    issue_key: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JiraOwnMove(Base):
    """A status move a run's own `jira.transition` made (7.3), so the delivery it causes does
    not start another run. Matched for 10 minutes by site, issue and status."""

    __tablename__ = "jira_own_moves"
    __table_args__ = (Index("ix_jira_own_moves_issue", "cloud_id", "issue_key", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    cloud_id: Mapped[str] = mapped_column(String(64))
    issue_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(255))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("runs.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    sandbox_ttl_s: Mapped[int | None] = mapped_column(Integer)
    branch_retention_days: Mapped[int | None] = mapped_column(Integer)
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
        # The queue sweep (`agentic_store.queue.requeue_stale_runs`).
        Index(
            "ix_runs_queued_unleased",
            "queued_at",
            postgresql_where=text("status = 'queued' AND lease_expires_at IS NULL"),
        ),
        # The expiry sweep (`agentic_store.expiry`).
        Index(
            "ix_runs_gate_expires_at",
            "gate_expires_at",
            postgresql_where=text("status = 'waiting'"),
        ),
        # The kept-sandbox sweep (`agentic_store.sandboxes`).
        Index(
            "ix_runs_sandbox_kept_until",
            "sandbox_kept_until",
            postgresql_where=text("sandbox_removed_at IS NULL"),
        ),
        # Listing runs, newest first.
        Index(
            "ix_runs_workspace_created", "workspace_id", text("created_at DESC"), text("id DESC")
        ),
        # A trigger's active run on an issue (`agentic_store.jira_triggers`).
        Index(
            "ix_runs_jira_trigger_active",
            "jira_trigger_id",
            postgresql_where=text(
                "jira_trigger_id IS NOT NULL AND status IN ('queued', 'running', 'waiting')"
            ),
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
    # A rerun from a step (12.4): `{node_id, use_wip, edited}`, the top-level step of `rerun_of`
    # it starts from, whether that step's uncommitted work is restored, and the parameter paths
    # changed (never their values). Null for a run that starts from the beginning.
    rerun_from: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    # What started the run: `manual` (a person, from the web), `api`, `rerun` or `jira` (7.3).
    trigger: Mapped[str] = mapped_column(String(32), server_default="api")
    # A run a Jira trigger started (7.3): the rule, and the issue `{cloud_id, site, key, url}`;
    # a rerun keeps the issue.
    jira_trigger_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jira_triggers.id", ondelete="SET NULL")
    )
    jira_issue: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
    # The issue as every agent of the run is told it (7.4, `agentic_engine.IssueBrief`): read
    # from Jira once, on the run's first attempt, and reused by its resumes and by a rerun from a
    # step. Null until read, and for a run with no `jira_issue`.
    jira_brief: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB)
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
    # When the run last became `queued` (created, decided at a gate, cancelled or expired while
    # waiting), and when the queue sweep last pushed its id again (`agentic_store.queue`). A
    # sweep never moves `queued_at`, so "Queued 4 min ago" stays true.
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The commit the run's first clone was at (12.2); its later sandboxes are cloned there, so
    # its saved branches apply and its agents read the same code. Null until it has a sandbox.
    base_sha: Mapped[str | None] = mapped_column(String(40))
    # Until when the sandbox of a failed or cancelled run is kept (12.3): the end event's
    # `sandbox_kept_until`, moved to now when a user asks to remove it. A worker's sweep removes it
    # after that and sets `sandbox_removed_at`. Null for a run whose sandbox was not kept.
    sandbox_kept_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sandbox_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class RunBranch(Base):
    """One saved version of a run's writer or integration branch (12.2), append only:
    `(run_id, branch, version)` is its key, versions are numbered per branch from 1, and a new
    one is written only when the branch's tip moved. `data` is a git bundle of the branch's
    commits on top of `base_sha` (`agentic_sandbox.export_branch`); the latest version of each
    writer and integration branch is fetched into a fresh sandbox.

    A `wip` version (12.3) is a writer's uncommitted work when its run failed or was cancelled,
    on `wip/<run>/<key>`; it is never restored. `changes` are the files the version changed on
    top of `base_sha`, as a gate shows them (`agentic_engine.gate.FileChange`), or
    `changes_error`. Past the run's `branch_retention_days`, `data` is dropped
    (`bundle_removed_at`); the row and its `changes` stay."""

    __tablename__ = "run_branches"
    __table_args__ = (
        CheckConstraint("kind IN ('writer', 'integration', 'wip')", name="ck_run_branches_kind"),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    branch: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The writer key the branch belongs to: a node id, `<orchestrator>.<task>`, or an
    # orchestrator's id for its integration branch.
    node_key: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    base_sha: Mapped[str] = mapped_column(String(40))
    head_sha: Mapped[str] = mapped_column(String(40))
    commits: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes | None] = mapped_column(LargeBinary)
    changes: Mapped[list[JsonValue] | None] = mapped_column(JSONB)
    changes_error: Mapped[str | None] = mapped_column(Text)
    # The top-level step the version was saved in (12.4): a rerun from a step restores the
    # versions saved before it. Null for versions saved before 12.4.
    step: Mapped[str | None] = mapped_column(String(128))
    bundle_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
