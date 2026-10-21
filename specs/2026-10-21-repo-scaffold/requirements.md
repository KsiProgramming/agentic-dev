# Repo scaffold

Roadmap phase: 0.1
Branch: plan/0.1-repo-scaffold

## Context
This is the first phase of Milestone 0 (walking skeleton), so it has no dependencies. It sets up the monorepo structure, local dev stack and CI that every later phase builds on. Building it as a working skeleton now follows mission principle 7 (*small, verifiable steps*): from 0.2 onward, each phase adds code and does not need to restructure the repo.

The scope is a little wider than the roadmap's "Done when". It also stubs the pieces that the tech stack already fixes and that 0.5–0.8 would otherwise have to retrofit:
- separate API and worker processes on Redis
- Postgres via async SQLAlchemy and Alembic
- a TypeScript client generated from FastAPI's OpenAPI spec

This phase unblocks 0.2 (spec models in `engine`), 0.3 (`runtime` package), 0.5 (migrations already in place) and 0.6/0.8 (typed API client and e2e tests ready).

## Scope
### In scope
- `uv` workspace (Python 3.12) with four packages: `api`, `engine`, `runtime`, `tools`. `runtime` and `tools` are importable stubs with one smoke test each.
- FastAPI app in `api`:
  - `GET /health`: liveness, no dependencies checked.
  - `GET /health/ready`: readiness, checks Postgres (`SELECT 1` via async SQLAlchemy) and Redis (`PING`). Returns 503 with the failing component when one is down.
- Alembic set up against Postgres with an empty baseline revision. The API image runs `alembic upgrade head` on start.
- Worker process stub (`python -m agentic_engine.worker`). It connects to Redis, logs "ready", writes a ready file for its container healthcheck, and idles until SIGTERM. It does not process jobs yet.
- Next.js (App Router, strict TS) app in `web/`: one empty page with Tailwind configured. No shadcn/ui components yet.
- OpenAPI → TS client pipeline:
  - a script exports `openapi.json` from the FastAPI app
  - a typed client is generated into `web/src/api/`
  - CI fails if the committed client is out of date
- `docker compose`: `postgres:16`, `redis`, `api`, `worker`, `web`, all with healthchecks.
- Tooling: `ruff` (lint + format), `pyright` strict, `pytest` + `pytest-asyncio`, Testcontainers. ESLint + Prettier, `tsc --noEmit`, Vitest + Testing Library, Playwright.
- GitHub Actions CI (see validation.md).

### Out of scope
- Workflow spec models and JSON Schema export (0.2)
- `AgentRuntime` interface (0.3)
- Any LangGraph code (0.4)
- Real tables and the `run_events` table (0.5); 0.1 only has an empty Alembic baseline
- Run endpoints and SSE (0.6)
- Queue job processing in the worker (0.4/0.6)
- Claude adapter (0.7)
- Monitor UI (0.8)
- shadcn/ui, React Flow, TanStack Query (added when first used: 0.8 / 2.5)
- Secrets/KMS (1.4)
- OpenTelemetry (9.3)
- Deployment and container registry publishing (9.5)

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Repo layout | `packages/{api,engine,runtime,tools}` (uv workspace members, imported as `agentic_api`, `agentic_engine`, …) + `web/` at the root | Matches the tech-stack package split. The `agentic_` prefix avoids clashes with generic top-level names like `tools`. Python and TS stay apart and share contracts only through JSON Schema / OpenAPI. |
| Health endpoints | `/health` (liveness) + `/health/ready` (Postgres + Redis) | Liveness meets "Done when". Readiness lets compose and CI wait on real dependencies. |
| Worker location | `agentic_engine.worker` module, own compose service, same image as the API | The tech stack separates API and worker processes. Workers will run engine graphs. |
| Queue library | Not chosen. The stub uses `redis.asyncio` directly. | Not fixed in the tech stack. We decide when the worker first consumes jobs (0.6). |
| TS client generator | `openapi-typescript` (types) + `openapi-fetch` (client) | Small, type-only output with no runtime codegen. Easy to check for drift in CI. Not fixed in the tech stack, so it is proposed here. |
| Node package manager | `pnpm`, Node 24 LTS | Fast, strict lockfile. Not fixed in the tech stack. Node 24 is the active LTS line. |
| Type checker | `pyright` strict | The tech stack allows mypy or pyright. Pyright is faster and stricter by default. |
| Migrations at start | API container runs `alembic upgrade head` before uvicorn | Keeps `docker compose up` a single command. We will revisit for SaaS deployment in 9.5. |

## Open questions
- None. Resolved during implementation: the Docker images are multi-stage now (the CI smoke test uses them), and `pnpm` + `openapi-typescript` were kept.
