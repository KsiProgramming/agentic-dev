from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

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
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, info: ConnectionInfo) -> "ConnectionOut":
        return cls(
            id=info.id,
            provider="github" if info.provider == "github" else "claude",
            key_hint=info.key_hint,
            account_login=info.account_login,
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
