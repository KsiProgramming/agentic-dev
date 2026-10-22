from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables."""

    # An empty variable (compose passes `${X:-}`) means unset.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, validate_by_name=True
    )

    database_url: str = "postgresql+asyncpg://agentic:agentic@localhost:5432/agentic"
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_s: float = 2.0
    # Browser origins allowed to call the API (the web app). Env: a JSON list.
    cors_origins: list[str] = ["http://localhost:3000"]
    # The master key that encrypts stored secrets (a 32-byte file). Unset, keys cannot be
    # stored.
    master_key_file: Path | None = None
    # The platform's GitHub App. With no id or slug, the GitHub endpoints answer 503.
    github_app_id: int | None = None
    github_app_slug: str | None = None
    github_app_private_key_file: Path | None = None
    # Where the web app is served: GitHub's install redirect sends the browser back there.
    web_base_url: str = "http://localhost:3000"
    # Where the browser reaches this API; the fake GitHub install flow redirects back to it.
    api_base_url: str = "http://localhost:8000"
    # `production` refuses the fakes (`claude_key_check`, `github`) (env `AGENTIC_ENV`).
    env: Literal["development", "production"] = Field(
        default="development", validation_alias="agentic_env"
    )
    # How a Claude key is checked before it is stored: one call to Anthropic, or (`fake`, for
    # dev and e2e tests) by its prefix, `sk-ant-test-`.
    claude_key_check: Literal["anthropic", "fake"] = "anthropic"
    # `fake` stands in a local GitHub App for dev and e2e tests (env `AGENTIC_GITHUB`).
    github: Literal["app", "fake"] = Field(default="app", validation_alias="agentic_github")
