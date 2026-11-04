# Getting started (contributors)

From a fresh clone to a running stack, passing tests and your first change. To deploy the platform for a team, see the [deployment guide](../operations/deployment.md) instead.

## 1. Tools

| Tool | Version | Used for |
|---|---|---|
| Docker + Compose v2 | recent | The local stack, run sandboxes, Testcontainers |
| [uv](https://docs.astral.sh/uv/) | 0.13+ | Python 3.12 workspace (installs Python for you) |
| Node.js | 24+ | Web app |
| pnpm | 11 (see `web/package.json`) | Web dependencies |
| git | 2.40+ | |

## 2. Run the stack

```bash
cp .env.example .env
docker compose up --build
```

Open <http://localhost:3000>. Agents run on the **fake runtime** (scripted, offline, free) until you set `AGENTIC_RUNTIME=claude`. Set `AGENTIC_GITHUB=fake` to work with two local demo repos without a GitHub App.

## 3. Run the checks

```bash
# Python
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"   # fast, no Docker
uv run pytest                        # everything; needs Docker (Testcontainers, sandbox image)

# Web
cd web
pnpm install
pnpm lint && pnpm format:check && pnpm typecheck && pnpm test
pnpm exec playwright install chromium
E2E_BASE_URL=http://localhost:3000 pnpm test:e2e   # against the running stack (axe + layout checks)
```

On Docker Desktop for Windows, set `TESTCONTAINERS_RYUK_DISABLED=true` if Testcontainers reports a port-mapping error. The Docker-backed sandbox tests need the sandbox image: `docker build -t agentic-dev/sandbox:dev packages/sandbox`.

## 4. Find your way around

| Path | What it is |
|---|---|
| [`specs/`](../../specs/) | The constitution: mission, roadmap, tech stack (contracts + decisions log), design language, and one dated folder per planned phase |
| `packages/engine` | Workflow spec, validator, graph ops, compiler to LangGraph, policy, templates |
| `packages/runtime` | `AgentRuntime` protocol, Claude and fake adapters, pricing |
| `packages/tools` | MCP tool servers (`repo`, `scan`, `artifacts`, `github`) |
| `packages/sandbox` | Per-run sandboxes (Docker, fake), worktrees, bundles; the sandbox image |
| `packages/github` | GitHub App client, fake, push |
| `packages/store` | Postgres models, event sink, queue, leases, audit |
| `packages/secrets` | Envelope encryption, key providers, redaction |
| `packages/api`, `packages/worker` | The two Python processes; Alembic migrations live in `packages/api/alembic` |
| `web/` | Next.js app; read `web/AGENTS.md` before writing Next.js code |
| `schemas/` | Exported JSON Schemas (generated; CI checks drift) |
| `scripts/` | Schema/OpenAPI export, roadmap and repo-rules tooling |

The [architecture overview](../architecture/overview.md) explains how these fit together, and the [developer reference](developer-reference.md) shows how each part is run and demonstrated locally.

## 5. Make a change

1. Find or propose the roadmap phase it belongs to ([`specs/roadmap.md`](../../specs/roadmap.md)). Larger work is planned first in `specs/YYYY-MM-DD-<slug>/` (`requirements.md`, `plan.md`, `validation.md`).
2. Branch from `main`.
3. Change code **and** the specs it affects in the same branch: a new API shape, library or UI rule goes in `specs/tech-stack.md` (with a decisions-log row if you chose between options).
4. If you change an endpoint: `uv run python scripts/export_openapi.py && (cd web && pnpm gen:api)`. If you change the spec models: `uv run python scripts/export_workflow_schema.py`.
5. Add a line under `## [Unreleased]` in [`CHANGELOG.md`](../../CHANGELOG.md).
6. For UI changes, follow the non-optional rules in [`CLAUDE.md`](../../CLAUDE.md) (tokens, display components, states) and look at the screen at 375 and 1440 px, light and dark.
7. Open a pull request. See [CONTRIBUTING.md](../../CONTRIBUTING.md).

The repository ships [Claude Code](https://claude.com/claude-code) skills in `.claude/skills/` (`plan-feature`, `open-pr`, `complete-phase`) that walk through this process; they are optional.
