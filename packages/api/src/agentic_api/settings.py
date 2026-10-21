from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agentic:agentic@localhost:5432/agentic"
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_s: float = 2.0
