# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Every pull request adds its changes under `[Unreleased]` before it is merged.** CI enforces this; add the `skip-changelog` label only to PRs with no user- or developer-visible change (for example a typo fix). On release, `[Unreleased]` is renamed to the version and date.

Use these headings: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. Write one line per change and link the PR.

## [Unreleased]

### Added
- Phase 0.1 repo scaffold ([#1](https://github.com/KsiProgramming/agentic-dev/pull/1)):
  - Planning package for phase 0.1 in `specs/2026-10-21-repo-scaffold/`.
  - `uv` workspace (Python 3.12) with the `api`, `engine`, `runtime` and `tools` packages; ruff, pyright strict, pytest with Testcontainers.
  - FastAPI app with `GET /health` (liveness) and `GET /health/ready` (Postgres and Redis; returns 503 and names the failing component).
  - Alembic setup with an empty `0001_baseline` revision, applied when the API container starts.
  - Worker process stub (`python -m agentic_engine.worker`) that connects to Redis, logs JSON, and stops cleanly.
  - Next.js web app (App Router, strict TypeScript, Tailwind) with an empty page, ESLint, Prettier, Vitest and Playwright.
  - Typed API client generated from the FastAPI OpenAPI spec (`scripts/export_openapi.py`, `pnpm gen:api`).
  - `docker compose` stack (Postgres 16, Redis 7, API, worker, web), with a healthcheck on every service.
  - GitHub Actions CI: Python, web, API contract drift check, and a compose smoke test with Playwright.
  - This changelog, and a CI check that requires each PR to update it.

[Unreleased]: https://github.com/KsiProgramming/agentic-dev/commits/main
