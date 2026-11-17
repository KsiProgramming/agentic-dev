from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentic_jira import Project
from agentic_store import JiraConnectionInfo, JiraProjectRef, JiraSiteInfo, JiraWebhookInfo

JiraStatus = Literal["not_connected", "connected", "needs_attention"]
# Why a connection needs attention: the refresh token was refused, the access token was (the
# app's access was removed), or the grant lacks a scope the platform asks for.
JiraAttentionReason = Literal["invalid_grant", "unauthorized", "scopes"]
WebhookState = Literal["listening", "not_needed", "failed"]

CloudId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")]
ProjectId = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[0-9]+$")]
# How many projects a workspace may pick on one site.
MAX_PROJECTS = 500


class StartAuthorize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_to: Annotated[
        str | None,
        Field(
            max_length=500,
            # A path of the web app only, never another origin (`//host`, `/\host`).
            pattern=r"^/([^/\\\s]\S*)?$",
            description="Where the web app lands after the consent. Defaults to the "
            "Integrations settings page.",
        ),
    ] = None


class AuthorizeUrlOut(BaseModel):
    """Where to send the browser to connect Jira. The URL is valid for 10 minutes."""

    authorize_url: str


class JiraProjectOut(BaseModel):
    id: str
    key: str
    name: str

    @classmethod
    def of(cls, project: JiraProjectRef | Project) -> "JiraProjectOut":
        project_id = project.id if isinstance(project, Project) else project.project_id
        return cls(id=project_id, key=project.key, name=project.name)


class JiraSiteOut(BaseModel):
    """A Jira site the connection reaches. `projects` are the ones the workspace may use
    there: nothing on a site is usable until some are picked, or while it is not `enabled`."""

    cloud_id: str
    url: str
    name: str
    enabled: bool
    projects: list[JiraProjectOut]

    @classmethod
    def of(cls, site: JiraSiteInfo) -> "JiraSiteOut":
        return cls(
            cloud_id=site.cloud_id,
            url=site.url,
            name=site.name,
            enabled=site.enabled,
            projects=[JiraProjectOut.of(p) for p in site.projects],
        )


class JiraWebhookOut(BaseModel):
    """Whether Jira can start the workspace's runs on a site: `listening` (a webhook is
    registered), `not_needed` (no enabled rule there) or `failed` (`error` says why:
    `url_conflict`, `limit`, `needs_attention`, `jira_unavailable`, `refused`, `no_url`)."""

    cloud_id: str
    state: WebhookState
    error: str | None = None
    expires_at: datetime | None = None
    renewed_at: datetime | None = None

    @classmethod
    def of(cls, info: JiraWebhookInfo) -> "JiraWebhookOut":
        state: WebhookState = (
            "failed"
            if info.error is not None
            else "listening"
            if info.webhook_id is not None
            else "not_needed"
        )
        return cls(
            cloud_id=info.cloud_id,
            state=state,
            error=info.error,
            expires_at=info.expires_at,
            renewed_at=info.renewed_at,
        )


class JiraConnectionOut(BaseModel):
    """The workspace's Jira connection. Its tokens are never returned."""

    configured: bool = Field(
        description="Whether the API has an Atlassian OAuth app. Without one nothing can connect."
    )
    status: JiraStatus
    reason: JiraAttentionReason | None = Field(
        default=None, description="Why it needs attention; connecting again clears it."
    )
    account: str | None = Field(
        default=None, description="The Atlassian account that consented; Jira acts as it."
    )
    scopes: list[str] = Field(default_factory=list[str], description="The scopes granted.")
    missing_scopes: list[str] = Field(
        default_factory=list[str], description="Scopes the platform asks for that it lacks."
    )
    sites: list[JiraSiteOut] = Field(default_factory=list[JiraSiteOut])
    webhooks: list[JiraWebhookOut] = Field(
        default_factory=list[JiraWebhookOut],
        description="Whether Jira can start runs on each site the workspace's triggers use (7.3).",
    )
    connected_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def of(
        cls,
        info: JiraConnectionInfo | None,
        *,
        configured: bool,
        missing: tuple[str, ...] = (),
        webhooks: list[JiraWebhookInfo] | None = None,
    ) -> "JiraConnectionOut":
        if info is None:
            return cls(configured=configured, status="not_connected")
        reason: JiraAttentionReason | None = None
        if info.needs_attention is not None:
            reason = (
                info.needs_attention
                if info.needs_attention in ("unauthorized", "scopes")
                else "invalid_grant"
            )
        return cls(
            configured=configured,
            status="connected" if reason is None else "needs_attention",
            reason=reason,
            account=info.account,
            scopes=list(info.scopes),
            missing_scopes=list(missing),
            sites=[JiraSiteOut.of(s) for s in info.sites],
            webhooks=[JiraWebhookOut.of(w) for w in webhooks or ()],
            connected_at=info.created_at,
            updated_at=info.updated_at,
        )


class PatchJiraSite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class JiraProjectPage(BaseModel):
    """A page of a site's projects, read live from Jira. Pass `next_cursor` as `cursor` for the
    next one."""

    projects: list[JiraProjectOut]
    next_cursor: int | None = None


class PutJiraProjects(BaseModel):
    """The whole list of projects the workspace may use on the site, by Jira project id."""

    model_config = ConfigDict(extra="forbid")

    project_ids: Annotated[list[ProjectId], Field(max_length=MAX_PROJECTS)]


class JiraErrorDetail(BaseModel):
    """The `detail` of a refused Jira request: `code` says what went wrong (`no_connection`,
    `needs_attention`, `unknown_project`), `message` says it for people."""

    code: str
    message: str
