# Python services (API and worker) share this image. Build context: repo root.

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock ./
COPY packages/api/pyproject.toml packages/api/
COPY packages/engine/pyproject.toml packages/engine/
COPY packages/runtime/pyproject.toml packages/runtime/
COPY packages/sandbox/pyproject.toml packages/sandbox/
COPY packages/secrets/pyproject.toml packages/secrets/
COPY packages/store/pyproject.toml packages/store/
COPY packages/tools/pyproject.toml packages/tools/
COPY packages/worker/pyproject.toml packages/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

COPY packages packages
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
# The worker clones run repos with git before copying them into their sandbox.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app
# Mount point of the master key volume; a new named volume takes this owner, so `app` can
# write the key there (compose `keygen`).
RUN mkdir /secrets && chown app:app /secrets && chmod 700 /secrets
COPY --from=build /app/.venv /app/.venv
COPY packages/api/alembic.ini /app/api/alembic.ini
COPY packages/api/alembic /app/api/alembic
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app/api
USER app
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=10 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).status == 200 else 1)"]

# Apply migrations, then serve. The worker service overrides this command.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn agentic_api:create_app --factory --host 0.0.0.0 --port 8000"]
