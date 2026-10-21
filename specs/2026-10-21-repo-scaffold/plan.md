# Plan: Repo scaffold

Order: backend → web → compose → CI. Each group adds its own lint/type/test tooling, so the repo stays green after every group.

## 1. Python workspace and API
- [ ] Root `pyproject.toml` declaring a uv workspace with members `packages/*`. Pin Python 3.12 in `.python-version`. Commit `uv.lock`.
- [ ] `packages/api`, `packages/engine`, `packages/runtime`, `packages/tools`: one `pyproject.toml` each, a `src/<name>/__init__.py`, and a `py.typed` marker.
- [ ] Root tool config:
  - `ruff` (lint + format)
  - `pyright` strict on all packages
  - `pytest` with `asyncio_mode = "auto"`
- [ ] `api`:
  - `create_app()` factory
  - settings via `pydantic-settings` (`DATABASE_URL`, `REDIS_URL`)
  - `GET /health` returning `{"status": "ok"}`
- [ ] `api`: async SQLAlchemy engine plus a Redis client, created in the lifespan and closed on shutdown. `GET /health/ready` pings both and returns 200, or 503 with `{"postgres": "...", "redis": "..."}`.
- [ ] Alembic: `packages/api/alembic/` with async `env.py` and an empty baseline revision.
- [ ] Tests:
  - unit: `/health` via `httpx.AsyncClient(transport=ASGITransport(app))`
  - integration: `/health/ready` against Testcontainers Postgres and Redis, both healthy and with Redis stopped (expect 503)
  - one import smoke test per stub package

## 2. Worker stub
- [ ] `engine.worker`: async `main()` that connects to Redis, logs a structured JSON "worker ready" line, and waits on SIGTERM/SIGINT for a clean shutdown.
- [ ] Test: start `main()` against Testcontainers Redis, send a cancel/stop signal, and assert a clean exit.

## 3. Web app and API client
- [ ] `web/`: Next.js App Router, strict TS, Tailwind. `app/page.tsx` renders an empty shell with a stable `data-testid="app-root"`. Use `pnpm` and Node 22, pinned through the `packageManager` field and `.nvmrc`.
- [ ] ESLint (Next config) + Prettier, plus `tsc --noEmit` script.
- [ ] Vitest + Testing Library: a render test for the page.
- [ ] OpenAPI pipeline:
  - `scripts/export_openapi.py` writes `web/openapi.json` from `create_app().openapi()`
  - `pnpm gen:api` runs `openapi-typescript` into `web/src/api/schema.d.ts`
  - `web/src/api/client.ts` wraps `openapi-fetch`
  - commit the generated files
- [ ] Playwright config and `e2e/home.spec.ts`: the page loads and `app-root` is visible. The base URL comes from env, so the same test runs against `pnpm dev` or compose.

## 4. Docker compose
- [ ] `packages/api/Dockerfile`: multi-stage, `uv sync --frozen`. Entrypoint runs `alembic upgrade head`, then `uvicorn`. The same image runs the worker with a different command.
- [ ] `web/Dockerfile`: multi-stage Next.js standalone build.
- [ ] `docker-compose.yml` services:
  - `postgres:16` and `redis:7`, both with healthchecks
  - `api` on :8000, depends on healthy DB and Redis, healthcheck on `/health/ready`
  - `worker`
  - `web` on :3000, healthcheck on `/`
- [ ] `.env.example` with dev-only values. No real secrets.
- [ ] README: a "Run locally" section (`docker compose up`, the URLs, how to run tests).

## 5. CI (GitHub Actions)
- [ ] `.github/workflows/ci.yml`, triggered on PR and on push to `main`. Jobs:
  - `python`: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pyright`, `pytest`. Testcontainers uses the runner's Docker.
  - `web`: `pnpm install --frozen-lockfile`, `lint`, `format:check`, `tsc`, `vitest run`.
  - `api-contract`: export OpenAPI, regenerate the client, then `git diff --exit-code web/openapi.json web/src/api/`.
  - `smoke`: `docker compose up -d --build --wait`, `curl -f :8000/health`, `curl -f :8000/health/ready`, `curl -f :3000`, Playwright against :3000. Always runs `docker compose logs` and `down -v` at the end.
- [ ] Cache uv and pnpm stores. Make the jobs required checks on `main`.
