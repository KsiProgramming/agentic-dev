# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Every pull request adds its changes under `[Unreleased]` before it is merged.** CI enforces this; add the `skip-changelog` label only to PRs with no user- or developer-visible change (for example a typo fix). On release, `[Unreleased]` is renamed to the version and date.

Use these headings: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. Write one line per change and link the PR.

## [Unreleased]

### Added
- Phase 1.1 sandbox manager: new `agentic_sandbox` package. `RepoSource` accepts an `https://` URL without credentials or a local path under `SANDBOX_LOCAL_ROOT`, with an optional ref. `clone_shallow` makes a depth-1 clone on the worker with only the https and file protocols enabled. There are two `SandboxManager` backends:
  - `DockerSandboxManager`: one container and volume per run, labelled `agentic.run_id`. The container has no network, a read-only root, no capabilities, a non-root user and resource limits. Both are removed when the run ends, and `sweep_orphans` removes leftovers at worker startup.
  - `FakeSandboxManager`: a temp directory on the worker, with no isolation.

  `SandboxTools` provides the first repo tool, `repo.list_files`, which runs inside the sandbox and refuses paths that leave the repo. `POST /runs` takes an optional `repo` (Alembic `0004_run_repo`) and returns `422` when a node uses `repo.*` tools without one. The worker opens a sandbox per run with a repo and gives its runtime the sandbox's tools. A sandbox that cannot be created ends the run with `run_failed` (`record_unstarted_run`). New settings: `SANDBOX_BACKEND`, `SANDBOX_IMAGE`, `SANDBOX_LOCAL_ROOT`, `DOCKER_GID`. `FakeRuntime(tools=...)` runs `CallTool` script steps, and with tools set it calls each tool a node names. Compose mounts the Docker socket and this repo's git history as a demo repo, and `scripts/sandbox_demo.py` runs the demo in the CI smoke job.
- Phase 0.8 minimal monitor page: the home page starts a sample run, and `/runs/[id]` lists the run's events live from the SSE stream (`useRunEvents` hook on `EventSource`, ordered and de-duplicated by `seq`, status from the final event, a "not found" state for unknown runs, payloads shown as text only). The API allows browser origins from `CORS_ORIGINS` and documents `RunEvent` in its OpenAPI spec, so the web client gets a generated type for it. Playwright checks that live events reach the browser within 1 s of being stored.
- Phase 0.7 Claude adapter: `agentic_runtime.claude.ClaudeRuntime` runs agent nodes on the Anthropic Messages API (`anthropic` SDK). It streams `text_delta` events, emits one `usage` event per API call, maps API errors to `failed` with a `retryable` flag, supports cooperative cancel, and has a tool-use loop over an injected `ToolExecutor` (`agentic_runtime.tools`, capped by `max_turns`). The worker picks the runtime with `AGENTIC_RUNTIME=fake|claude` and reads `ANTHROPIC_API_KEY` (as a secret), `CLAUDE_MODEL`, `CLAUDE_MAX_TOKENS` and `CLAUDE_MAX_TURNS`; it fails fast without a key. Test helpers in `agentic_runtime.testing`: `MockClaude` (real SDK on an in-memory transport), `ScriptedToolExecutor` and `collect_and_check`.
- Phase 0.6 runs API: `POST /runs` (inline spec + input → `202` with `run_id` and `events_url`) and `GET /runs/{id}/events`, a Server-Sent Events stream (`fastapi.sse`) that replays stored events after `Last-Event-ID` or `?after=`, follows live ones through Postgres `LISTEN/NOTIFY`, and ends after the final run event. New `agentic_worker` package: the worker takes run ids from a Redis queue (`agentic_store.enqueue_run` / `dequeue_run`) and runs them with `PostgresEventSink`; stopping it cancels the run in flight. Alembic revision `0003_run_spec` stores each run's spec and input. `agentic_store` gains `create_run`, `get_run` and `listen`. `FakeRuntime(default=...)` and `slow_echo_script` pace fake runs (`FAKE_STEP_DELAY_S`).
- Phase 0.5 run event log: `agentic_engine.events` (`RunEvent`, `EventSink`, `InMemoryEventSink`). `run_workflow(..., run_id=, sink=)` writes run and node lifecycle events plus every agent event, numbered by `seq`, and `WorkflowRunResult` now carries `run_id`. New `agentic_store` package with SQLAlchemy models, `PostgresEventSink` and `list_run_events`. Alembic revision `0002_run_events` adds the `runs` table and the append-only `run_events` table. The migration test now checks models against migrations.
- Phase 0.4 spec → LangGraph compiler: `agentic_engine.graph` with `compile_workflow` (nested sequences flattened to a chain of agent nodes named by spec id, a node that does not complete ends the run) and `run_workflow` (output of one node becomes the next node's input; returns status, order, per-node results and summed usage). Adds the `langgraph` dependency, typed stubs in `typings/langgraph/`, and `agentic_engine.agent.sum_usage`.
- Phase 0.3 `AgentRuntime` interface and fake runtime: provider-neutral request and event models (`text_delta`, `message`, `tool_call`, `tool_result`, `usage`, `completed`/`failed`/`cancelled`) with a contract checker in `agentic_runtime`, cooperative cancellation, a scripted `FakeRuntime`, `agentic_engine.agent.run_agent_node`, and a no-network guard for the runtime and engine tests.
- Phase 0.2 workflow spec v0: Pydantic models in `agentic_engine.spec` (`agent` and `sequence` nodes, unique slug ids, unknown keys rejected), a generated JSON Schema in `schemas/workflow-spec.v0.json` (`scripts/export_workflow_schema.py`) with a CI freshness check, and valid/invalid spec fixtures with tests.
- `plan-feature` Claude Code skill (`.claude/skills/plan-feature/`) that finds the next unplanned phase in `specs/roadmap.md`, interviews the user, and writes its `plan.md`, `requirements.md` and `validation.md`.
- `complete-phase` Claude Code skill (`.claude/skills/complete-phase/`) and `scripts/check_roadmap.py --mark-done <pr-url>`, which set an implemented phase's Status to `✅ Done` in `specs/roadmap.md`. The `Roadmap phase marked done` PR check now commits this to same-repo PR branches before checking it.
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
  - `Status` column in `specs/roadmap.md` (phase 0.1 marked done), and a CI check (`scripts/check_roadmap.py`) that requires a PR implementing a phase to mark it done.

### Changed
- The `two-step-sequence.json` spec fixture no longer lists `repo.*` tools, since a run that uses them now needs a `repo`. `list-repo-files.json` is the fixture for repo tools.
- The worker image installs `git`, and the worker builds its runtime per run (sharing one Claude client) so each run's agents get its own sandbox tools.
- Worker and API tests no longer read the developer's `.env`, so they never run on Claude with a real key by accident.
- The worker moved from `agentic_engine.worker` to the `agentic_worker` package (`python -m agentic_worker`); `agentic_engine` no longer depends on Redis or pydantic-settings.
- `PostgresEventSink` no longer creates the `runs` row: create it with `create_run` first, and `run_started` moves it from `queued` to `running`.

[Unreleased]: https://github.com/KsiProgramming/agentic-dev/commits/main
