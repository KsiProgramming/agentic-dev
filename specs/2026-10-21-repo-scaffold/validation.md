# Validation: Repo scaffold

## Done when (from roadmap)
> `docker compose up` serves a health endpoint and an empty web page; CI is green

## Automated checks
- [ ] `python` job:
  - `ruff check` and `ruff format --check` are clean
  - `pyright` strict reports 0 errors
  - `pytest` passes, including:
    - `test_health_returns_ok`: `GET /health` returns 200 `{"status": "ok"}`
    - `test_ready_ok`: `/health/ready` returns 200 with Testcontainers Postgres and Redis up
    - `test_ready_redis_down`: `/health/ready` returns 503 and names `redis`
    - `test_worker_starts_and_stops`: the worker connects to Redis, writes its ready file, and exits cleanly on stop
    - `test_upgrade_head_reaches_baseline`: Alembic migrates Testcontainers Postgres to `0001_baseline`
    - an import smoke test for `runtime` and `tools`
- [ ] `web` job: ESLint, Prettier check, `tsc --noEmit` and the Vitest page render test all pass.
- [ ] `api-contract` job: the regenerated `openapi.json` and TS client match the committed files.
- [ ] `smoke` job:
  - `docker compose up -d --build --wait` succeeds (all healthchecks pass)
  - `curl -f` on `/health`, `/health/ready` and `:3000` succeeds
  - Playwright `home.spec.ts` passes

## Manual / demo checks
- [ ] From a clean clone, run `cp .env.example .env && docker compose up --build`. All five services reach healthy.
- [ ] `curl localhost:8000/health` returns `{"status":"ok"}`.
- [ ] `curl localhost:8000/health/ready` returns 200.
- [ ] Run `docker compose stop redis`. `/health/ready` now returns 503 naming redis. Start Redis again and it returns 200.
- [ ] Opening `http://localhost:3000` shows the empty page with no console errors.
- [ ] `docker compose logs worker` shows the "worker ready" line. `docker compose stop worker` exits cleanly (no traceback).
- [ ] `docker compose exec postgres psql -U agentic -d agentic -c 'select * from alembic_version'` shows `0001_baseline`.

## Merge criteria
- [ ] All CI jobs above are green on the PR.
- [ ] `uv.lock` and `pnpm-lock.yaml` are committed, and CI installs with frozen lockfiles.
- [ ] README "Run locally" section is updated and verified from a clean clone.
- [ ] No real secrets in the repo; `.env` is git-ignored and only `.env.example` is committed.
- [ ] Open questions in requirements.md are resolved or explicitly deferred.
