# Plan: Repo scaffold

Order: backend → web → compose → CI. Each group adds its own lint/type/test tooling, so the repo stays green after every group.

## 1. Python workspace and API
- [x] Root `pyproject.toml` declaring a uv workspace with members `packages/*`. Pin Python 3.12 in `.python-version`. Commit `uv.lock`.
- [x] `packages/api`, `packages/engine`, `packages/runtime`, `packages/tools`: one `pyproject.toml` each, a `src/<name>/__init__.py`, and a `py.typed` marker.
- [x] Root tool config:
  - `ruff` (lint + format)
  - `pyright` strict on all packages
  - `pytest` with `asyncio_mode = "auto"`
- [x] `api`:
  - `create_app()` factory
  - settings via `pydantic-settings` (`DATABASE_URL`, `REDIS_URL`)
  - `GET /health` returning `{"status": "ok"}`
- [x] `api`: async SQLAlchemy engine plus a Redis client, created in the lifespan and closed on shutdown. `GET /health/ready` pings both and returns 200, or 503 with `{"postgres": "...", "redis": "..."}`.
- [x] Alembic: `packages/api/alembic/` with async `env.py` and an empty baseline revision.
- [x] Tests:
  - unit: `/health` via `httpx.AsyncClient(transport=ASGITransport(app))`
  - integration: `/health/ready` against Testcontainers Postgres and Redis, both healthy and with Redis stopped (expect 503)
  - one import smoke test per stub package
  - `alembic upgrade head` reaches the baseline revision on Testcontainers Postgres

## 2. Worker stub
- [x] `agentic_engine.worker`: async `main()` that connects to Redis, logs a structured JSON "worker ready" line, touches an optional ready file (used by the compose healthcheck), and waits on SIGTERM/SIGINT for a clean shutdown.
- [x] Test: start `main()` against Testcontainers Redis, send a cancel/stop signal, and assert a clean exit.

## 3. Web app and API client
- [x] `web/`: Next.js App Router, strict TS, Tailwind. `app/page.tsx` renders an empty shell with a stable `data-testid="app-root"`. Use `pnpm` and Node 24, pinned through the `packageManager` field and `.nvmrc`.
- [x] ESLint (Next config) + Prettier, plus `tsc --noEmit` script.
- [x] Vitest + Testing Library: a render test for the page.
- [x] OpenAPI pipeline:
  - `scripts/export_openapi.py` writes `web/openapi.json` from `create_app().openapi()`
  - `pnpm gen:api` runs `openapi-typescript` into `web/src/api/schema.d.ts`
  - `web/src/api/client.ts` wraps `openapi-fetch`
  - commit the generated files
- [x] Playwright config and `e2e/home.spec.ts`: the page loads and `app-root` is visible. The base URL comes from env, so the same test runs against `pnpm dev` or compose.

## 4. Docker compose
- [x] `packages/api/Dockerfile`: multi-stage, `uv sync --frozen`. Entrypoint runs `alembic upgrade head`, then `uvicorn`. The same image runs the worker with a different command.
- [x] `web/Dockerfile`: multi-stage Next.js standalone build.
- [x] `docker-compose.yml` services:
  - `postgres:16` and `redis:7`, both with healthchecks
  - `api` on :8000, depends on healthy DB and Redis, healthcheck on `/health/ready`
  - `worker`, healthcheck on its ready file
  - `web` on :3000, healthcheck on `/`
- [x] `.env.example` with dev-only values. No real secrets.
- [x] README: a "Run locally" section (`docker compose up`, the URLs, how to run tests).

## 5. CI (GitHub Actions)
- [x] `.github/workflows/ci.yml`, triggered on PR and on push to `main`. Jobs:
  - `python`: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pyright`, `pytest`. Testcontainers uses the runner's Docker.
  - `web`: `pnpm install --frozen-lockfile`, `lint`, `format:check`, `tsc`, `vitest run`.
  - `api-contract`: export OpenAPI, regenerate the client, then `git diff --exit-code web/openapi.json web/src/api/`.
  - `smoke`: `docker compose up -d --build --wait`, `curl -f :8000/health`, `curl -f :8000/health/ready`, `curl -f :3000`, Playwright against :3000. Always runs `docker compose logs` and `down -v` at the end.
- [x] Cache uv and pnpm stores.
- [ ] Make the jobs required checks on `main` (repo settings, after the first green run).
