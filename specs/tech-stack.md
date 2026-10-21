# Tech Stack

Decision summary: **Python backend with LangGraph as the orchestration engine**, and a **Next.js/TypeScript frontend**. The two sides share contracts through JSON Schema, not shared code.

## Backend (Python)

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12+ | Typed with type hints everywhere. `mypy`/`pyright` runs in strict mode in CI. |
| Packaging | `uv` | Lockfile committed. One workspace with several packages (api, engine, runtime, tools). |
| API | FastAPI | REST plus SSE (`GET /runs/{id}/events`). The OpenAPI spec is generated and feeds the frontend client. |
| Models / validation | Pydantic v2 | Workflow spec, graph operations, node manifests and events. Exported as JSON Schema. |
| Orchestration engine | LangGraph | The workflow spec compiles to a LangGraph graph. Primitives map to nodes or subgraphs. `map`/`orchestrator` use `Send` for dynamic fan-out. `gate` uses `interrupt()`. |
| Durable state | LangGraph Postgres checkpointer | A run resumes from the last completed node after a worker restart (AC-8). |
| Run workers | Background worker processes pulling from a queue (Redis-backed) | API and workers are separate processes. Workers are stateless apart from checkpoints. |
| Expressions | CEL (`cel-python`) | Sandboxed conditions and mappings (`router`, `loop.until`, input mapping). Arbitrary code is never allowed. |
| Database | PostgreSQL 16 | Workspaces, connections, repos, node types, workflows (versioned, immutable once published), runs, node runs, approvals. |
| Event log | Append-only `run_events` table in Postgres plus Postgres `LISTEN/NOTIFY` for SSE fan-out | The single source for the monitor, cost view and audit. |
| Migrations | Alembic | |
| ORM | SQLAlchemy 2.x (async) | |

## Agent runtime

One `AgentRuntime` interface (start → async iterator of `AgentEvent`, plus cancel), with two adapters:

| Adapter | Library | Auth |
|---|---|---|
| Claude | Claude Agent SDK (Python), or our own tool loop on the Anthropic Messages API | User's API key, encrypted with a KMS key per workspace |
| GitHub Copilot | GitHub Copilot SDK (Python binding) | GitHub OAuth / platform GitHub App |

- Both adapters emit one normalised usage event (tokens, premium requests, estimated USD).
- Validation flags capability gaps (for example a structured output mode) before the run starts.
- Default models: the latest Claude models (Opus for hubs, reviewers and the Flow Architect; Sonnet or Haiku for map workers). The Architect can override these within policy.

## Tool layer

- **MCP servers** owned by the platform: `repo` (read/write in the sandbox), `tests`, `github`, `jira`, plus plugin nodes. Built with the official MCP Python SDK.
- Tools are granted per node through the node manifest. Audit agents get read-only tools.
- Credentials stay inside the tool servers. Agents never see them.

## Integrations

- **GitHub:** GitHub App (installation tokens, webhooks for PR comments, check runs and labels). Library: `githubkit`.
- **Jira:** Atlassian OAuth 2.0 (3LO) per workspace, scoped to selected projects. Webhooks trigger runs on status or label changes.
- No personal access tokens are stored.

## Sandbox

- One container per run (Docker locally; gVisor or Firecracker microVMs in production). No host access.
- Shallow clone per run, one git worktree and branch per parallel writer (`agent/<run-id>/<node-id>`).
- Network egress is limited to an allowlist (package registries, GitHub, the model provider).
- Plugin nodes run in their own sandbox with only the permissions they declare.

## Frontend (TypeScript)

| Concern | Choice |
|---|---|
| Framework | Next.js (App Router) + TypeScript (strict) |
| Canvas & monitor | React Flow (`@xyflow/react`) |
| Side panels | JSON-Schema forms (`@rjsf/core`), rendered from node manifests |
| Editors / diffs | Monaco |
| Data | TanStack Query + SSE (`EventSource`) |
| API client | Generated from FastAPI's OpenAPI spec |
| Styling | Tailwind CSS + shadcn/ui |

## Security & secrets

- Secrets are encrypted with a KMS key per workspace (cloud KMS in production; a local key file in dev). They never appear in logs or agent context.
- Policy limits are enforced in the engine at validation time and at runtime:
  - **Budget (USD): optional.** No default cap. If set, it is a hard stop at 100%. If unset, the run continues and cost is still tracked.
  - Agents alive 8, agents spawned 40, nesting depth 2, loop iterations 5, wall time 2 h, gates before push/PR/repo creation/Jira status change.

## Observability

- OpenTelemetry traces across API, engine nodes and tool calls.
- Cost and token metrics per node, run, user and workspace, derived from usage events.
- Structured JSON logs with secrets redacted.

## Testing & quality

- Backend: `pytest` + `pytest-asyncio`. A fake `AgentRuntime` provides deterministic engine tests. Testcontainers runs Postgres.
- Frontend: Vitest + Testing Library; Playwright for end-to-end tests.
- Lint/format: `ruff` (Python), ESLint + Prettier (TS).
- Flow Architect evaluation set: goal and repo pairs, run in CI on a schedule.

## Infrastructure & delivery

- Local dev: `docker compose` (Postgres, Redis, API, worker, frontend).
- CI: GitHub Actions.
- Hosting: SaaS only (v1). Containerised services on a managed Kubernetes or container platform. The cloud provider is still to be decided.

## Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Engine | LangGraph (not Temporal) | Python-native and agent-oriented, with built-in interrupts for gates and `Send` for dynamic fan-out. Durability comes from the Postgres checkpointer. |
| Backend language | Python | Matches LangGraph and has a strong agent/MCP SDK ecosystem. |
| Frontend | Next.js/TS | As specified by stakeholders. Contracts are shared through JSON Schema. |
| Hosting | SaaS only | v1 scope (see mission). |
