from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import SecretStr

from agentic_jira.errors import JiraConfigError


@dataclass(frozen=True)
class AtlassianAppConfig:
    """The deployment's Atlassian OAuth 2.0 (3LO) app: its client id and secret, and the
    callback URL registered for it (`<API>/jira/callback`)."""

    client_id: str
    client_secret: SecretStr
    redirect_uri: str

    @classmethod
    def from_file(cls, client_id: str, client_secret_file: Path, redirect_uri: str) -> Self:
        try:
            secret = client_secret_file.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise JiraConfigError(
                f"cannot read the Atlassian client secret {client_secret_file}: "
                f"{type(exc).__name__}"
            ) from None
        if not secret:
            raise JiraConfigError(f"{client_secret_file} is empty")
        return cls(client_id=client_id, client_secret=SecretStr(secret), redirect_uri=redirect_uri)
