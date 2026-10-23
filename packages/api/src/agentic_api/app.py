import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agentic_api.github.routes import router as github_router
from agentic_api.health import router as health_router
from agentic_api.runs.listener import RunEventListener
from agentic_api.runs.routes import router as runs_router
from agentic_api.settings import Settings
from agentic_api.templates.routes import router as templates_router
from agentic_api.workflows.routes import router as workflows_router
from agentic_api.workspaces.claude_keys import (
    AnthropicKeyVerifier,
    ClaudeKeyVerifier,
    FakeKeyVerifier,
)
from agentic_api.workspaces.routes import router as workspaces_router
from agentic_engine.events import RunEvent
from agentic_github import (
    FakeGithubApp,
    GithubApp,
    GithubAppConfig,
    GithubConfigError,
    GithubPlatform,
)
from agentic_secrets import LocalKeyProvider, install_redaction

# Loggers with their own handlers when uvicorn serves the app; the rest propagate to root.
_LOGGERS_WITH_HANDLERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


class FakeInProductionError(RuntimeError):
    """A fake meant for dev and tests is configured with `AGENTIC_ENV=production`."""


def create_app(
    settings: Settings | None = None, *, claude_keys: ClaudeKeyVerifier | None = None
) -> FastAPI:
    """Tests pass `claude_keys`; otherwise the settings choose how Claude keys are checked."""
    settings = settings or Settings()
    _refuse_fakes_in_production(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        for name in _LOGGERS_WITH_HANDLERS:
            install_redaction(logging.getLogger(name))
        db = create_async_engine(settings.database_url, pool_pre_ping=True)
        redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
            settings.redis_url,
            socket_connect_timeout=settings.readiness_timeout_s,
            socket_timeout=settings.readiness_timeout_s,
        )
        run_events = RunEventListener(settings.database_url)
        listening = asyncio.create_task(run_events.run())
        app.state.db = db
        app.state.sessions = async_sessionmaker(db, expire_on_commit=False)
        app.state.redis = redis
        app.state.run_events = run_events
        try:
            yield
        finally:
            listening.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listening
            await redis.aclose()
            await db.dispose()
            if app.state.github is not None:
                app.state.github.close()

    app = FastAPI(title="Agentic Dev Platform API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    # A configured but unreadable master key fails here, at startup, not on a request.
    app.state.keys = (
        LocalKeyProvider.from_file(settings.master_key_file) if settings.master_key_file else None
    )
    app.state.github = _github_app(settings)
    app.state.claude_keys = claude_keys or (
        FakeKeyVerifier() if settings.claude_key_check == "fake" else AnthropicKeyVerifier()
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type", "last-event-id"],
    )
    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(workspaces_router)
    app.include_router(github_router)
    app.include_router(templates_router)
    app.include_router(workflows_router)
    app.add_exception_handler(RequestValidationError, _validation_error)
    _add_schema_components(app, RunEvent)
    return app


def _refuse_fakes_in_production(settings: Settings) -> None:
    if settings.env != "production":
        return
    for name, fake in (
        ("AGENTIC_GITHUB", settings.github == "fake"),
        ("CLAUDE_KEY_CHECK", settings.claude_key_check == "fake"),
    ):
        if fake:
            raise FakeInProductionError(f"{name}=fake is not allowed with AGENTIC_ENV=production")


def _github_app(settings: Settings) -> GithubPlatform | None:
    """The GitHub App, if its id and slug are set (or the fake one). A missing or unreadable
    private key then fails here, at startup."""
    if settings.github == "fake":
        return FakeGithubApp(settings.api_base_url)
    if settings.github_app_id is None or settings.github_app_slug is None:
        return None
    if settings.github_app_private_key_file is None:
        raise GithubConfigError("GITHUB_APP_PRIVATE_KEY_FILE must be set with GITHUB_APP_ID")
    return GithubApp(
        GithubAppConfig.from_file(
            settings.github_app_id, settings.github_app_slug, settings.github_app_private_key_file
        )
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422 echoes each invalid value back. Bodies under /workspaces carry
    secrets, so their errors keep only where and why."""
    assert isinstance(exc, RequestValidationError)
    if not request.url.path.startswith("/workspaces"):
        return await request_validation_exception_handler(request, exc)
    errors = [
        {k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


def _add_schema_components(app: FastAPI, *models: type[BaseModel]) -> None:
    """Add `models` to the OpenAPI components. FastAPI only collects models from request
    and response bodies, but SSE frames reference `RunEvent` and the web client needs its type."""
    build = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schemas = build().setdefault("components", {}).setdefault("schemas", {})
            for model in models:
                schema = model.model_json_schema(
                    mode="serialization", ref_template="#/components/schemas/{model}"
                )
                schemas.update(schema.pop("$defs", {}))
                schemas[model.__name__] = schema
        return build()

    app.openapi = openapi
