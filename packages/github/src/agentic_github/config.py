from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import SecretStr

from agentic_github.errors import GithubConfigError

_PEM_HEADER = "-----BEGIN"


@dataclass(frozen=True)
class GithubAppConfig:
    """The platform's GitHub App: its id, its URL slug and its private key (PEM)."""

    app_id: int
    slug: str
    private_key: SecretStr

    @classmethod
    def from_file(cls, app_id: int, slug: str, private_key_file: Path) -> Self:
        try:
            pem = private_key_file.read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError) as exc:
            raise GithubConfigError(
                f"cannot read the GitHub App private key {private_key_file}: {type(exc).__name__}"
            ) from None
        if not pem.lstrip().startswith(_PEM_HEADER):
            raise GithubConfigError(f"{private_key_file} is not a PEM private key")
        return cls(app_id=app_id, slug=slug, private_key=SecretStr(pem))
