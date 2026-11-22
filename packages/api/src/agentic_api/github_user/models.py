from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agentic_store import GithubUserInfo

GithubUserStatus = Literal["connected", "needs_attention"]
# Why a connection needs attention: the refresh token was refused, or the access token was (the
# person revoked the app, or their Copilot access ended).
GithubUserAttentionReason = Literal["invalid_grant", "unauthorized"]


class StartGithubUserAuthorize(BaseModel):
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


class GithubUserAuthorizeOut(BaseModel):
    """Where to send the browser to connect a personal GitHub account. Valid for 10 minutes."""

    authorize_url: str


class GithubUserConnectionOut(BaseModel):
    """One person's connection. The token is never returned."""

    id: UUID
    login: str = Field(description="The GitHub account that connected; its Copilot is used.")
    status: GithubUserStatus
    reason: GithubUserAttentionReason | None = Field(
        default=None, description="Why it needs attention; connecting again clears it."
    )
    connected_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, info: GithubUserInfo) -> "GithubUserConnectionOut":
        reason: GithubUserAttentionReason | None = None
        if info.needs_attention is not None:
            reason = "unauthorized" if info.needs_attention == "unauthorized" else "invalid_grant"
        return cls(
            id=info.id,
            login=info.login,
            status="connected" if info.needs_attention is None else "needs_attention",
            reason=reason,
            connected_at=info.created_at,
            updated_at=info.updated_at,
        )


class GithubUserConnectionsOut(BaseModel):
    """The workspace's personal GitHub connections, one per person."""

    configured: bool = Field(
        description="Whether the API has an OAuth app for personal connections. Without one "
        "nothing can connect."
    )
    connections: list[GithubUserConnectionOut]
