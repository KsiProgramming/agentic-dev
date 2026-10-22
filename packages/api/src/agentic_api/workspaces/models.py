from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from agentic_github import installation_settings_url
from agentic_store import ConnectionInfo, WorkspaceInfo

Provider = Literal["claude", "github"]


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    @classmethod
    def of(cls, info: WorkspaceInfo) -> "WorkspaceOut":
        return cls(id=info.id, name=info.name, created_at=info.created_at)


class ConnectionOut(BaseModel):
    """A stored connection. Its secret is never returned; `key_hint` is its last 4 characters.

    A GitHub connection has no secret: it shows the account the App is installed on instead."""

    id: UUID
    provider: Provider
    key_hint: str | None = None
    account_login: str | None = None
    manage_url: str | None = Field(
        default=None,
        description="GitHub: the installation's settings page, where its owner picks the repos "
        "it reaches. Unset for connections made before the account type was recorded.",
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, info: ConnectionInfo) -> "ConnectionOut":
        manage_url = (
            installation_settings_url(info.installation_id, info.account_login, info.account_type)
            if info.installation_id is not None
            and info.account_login is not None
            and info.account_type is not None
            else None
        )
        return cls(
            id=info.id,
            provider="github" if info.provider == "github" else "claude",
            key_hint=info.key_hint,
            account_login=info.account_login,
            manage_url=manage_url,
            created_at=info.created_at,
            updated_at=info.updated_at,
        )


class PutClaudeConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(
        min_length=8,
        max_length=512,
        description="The Anthropic API key. Stored encrypted; it is never returned.",
        json_schema_extra={"writeOnly": True, "format": "password"},
    )


class ConnectionErrorDetail(BaseModel):
    """The `detail` of a refused connection: `code` says what went wrong (`invalid_key`,
    `verify_unavailable`), `message` says it for people."""

    code: str
    message: str
