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
| Styling | Tailwind CSS v4 with design tokens as CSS variables (light + dark) |
| Components | shadcn/ui (Radix primitives, code copied into `web/src/components/ui`) |
| Icons / fonts | `lucide-react`; Inter (UI) and JetBrains Mono (code, ids) via `next/font` |
| Toasts / theme | `sonner`, `next-themes` |
| JSON / Markdown display | Collapsible JSON viewer, `react-markdown` (no raw HTML) for agent messages |
| A11y / visual checks | `@axe-core/playwright`, Playwright screenshots at 375 / 768 / 1440 px |

## UI design system

The UI follows the mission's "Enterprise-grade, calm UI" principle. Every screen is built from these rules. If a phase needs a new pattern, it is added here first.

### Look

- **Style:** modern and minimal, in the spirit of Linear, Vercel and GitHub. Neutral greys (zinc) on white, or on near-black in dark mode, with one accent colour (indigo) for primary actions and focus. Light borders, very small shadows and rounded corners (`--radius: 0.5rem`). No gradients and no decoration.
- **Colour means status only:** `running` blue, `waiting` amber, `succeeded` green, `failed` red, `cancelled` and `queued` grey. Status is always shown as icon + label, never colour alone.
- **Tokens:** every colour, radius and shadow is a semantic token (`--background`, `--foreground`, `--muted`, `--border`, `--primary`, `--status-*`). Components never use raw palette classes such as `bg-red-100`.
- **Type:** Inter at 14 px base for UI text, 13 px for dense tables. JetBrains Mono for ids, paths, code and JSON. Numbers use `tabular-nums`.
- **Theme:** light, dark and system, switched from the top bar.

### Layout

- **App shell:** a left sidebar (Runs, Templates, Settings; workspace switcher at the top) and a top bar (breadcrumbs, theme, user). The sidebar collapses to icons from 1024 to 1279 px and becomes a drawer below 1024 px.
- **Breakpoints:** mobile-first. Designed and tested at 375, 768, 1024 and 1440 px. No horizontal page scroll at any width. Wide content (JSON, logs) scrolls inside its own box.
- **Page header:** title, short description and primary actions on the right. On mobile the actions stack below the title.
- **Tables on desktop, cards on mobile:** a list keeps its columns at ≥ 768 px and turns into stacked cards below that.
- **States:** every data view has a skeleton loader, an empty state (icon, one sentence, primary action) and an error state (message plus Retry).

### Start and settings

- **Template gallery (`/templates`):** one card per template from `GET /templates`, showing an icon, name, description and a "Requires" line with one chip per connection (Claude, GitHub). Each chip shows connected or missing. Clicking a card opens the "New run" sheet; `/templates?template=<id>` opens it directly.
- **"New run" sheet:** a side sheet (right, 480 px) from 768 px, and a full-height bottom sheet below that. It is opened from a gallery card or from the "New run" action in the Runs page header (which adds a template picker). From top to bottom it shows:
  - a "Before you start" checklist of the template's required connections, with a Claude key entered inline and GitHub connected through the install flow;
  - the repo;
  - the template's fields;
  - a sticky footer with Cancel and Start run.

  Start run stays disabled until every required connection is there.
- **Template fields:** rendered from the template's JSON Schema, never hand-coded per template. Each field has a label (`title`), help text (`description`) and an inline error under it. Client checks mirror the schema's limits. A server 422 is shown on the field it names. An unsupported schema shows an error state, not a partial form.
- **Combobox (repo picker):** a button that opens a searchable list (Command + Popover). Each repo shows `owner/name` in mono, a lock icon if private, and its default branch. It is keyboard first: type to filter, arrows, Enter. The last used repo is preselected if it is still listed. The list ends with an "Add repos on GitHub" link.
- **Form errors:** on the field, in `--destructive` text with an icon, tied to it by `aria-describedby`. Form-level errors (network, 5xx) go in an `Alert` above the footer. Submit buttons show a spinner and are disabled while pending.
- **Connection card (Settings):** icon, name and a one-line purpose; a status badge (Connected green, Not connected grey, Needs attention amber), the account or key hint, and actions on the right (stacked below on mobile). Disconnect and Remove ask for confirmation in a dialog. A provider the server cannot use (no GitHub App configured) shows a muted card with the reason and no action.

### Run console

- **Header:** status badge, workflow name, repo and branch, started time and duration, and the PR link once opened. Actions: Rerun, Cancel, Copy run id.
- **Timeline (default tab):** the run reads top to bottom on a vertical rail. Each node hangs off it by a status icon (with a screen-reader label) and shows its duration; a finished node has no badge, and only states that need attention say so in words ("Needs approval", "Failed"). Map items (named by their path) and loop iterations are nested on their own rail. Inside a step:
  - Streamed `text_delta` events are **merged on the client** into one growing message per agent turn. The `message` event replaces the merged text when it arrives. A message is rendered as Markdown with raw HTML and images dropped, so payloads stay data.
  - Each tool call is one quiet line with an icon, a verb and its target ("Read `src/app.ts`"); opening it shows its arguments and result (JSON pretty-printed, collapsed after 2 levels, copyable). Consecutive reads, listings and searches collapse into one summary line ("Read 12 files, listed 3 folders"). Calls that change something (writes, commits, pull requests) and failed calls stand on their own line with a preview of their first lines. Only running and failed calls get a status icon.
  - Usage and cost appear as a quiet footer line.
- **Raw events tab:** the event table, with filters by type and node. Consecutive chunks of one message are folded into one row (expandable to the chunks). It is kept for debugging and audit.
- **Graph tab:** added in 3.5.
- **Approval dock:** while a gate is waiting, a bar is fixed to the bottom of the viewport with:
  - the gate title;
  - a one-line summary: the gate's prompt, else the first line of its artifact;
  - "Review details", which opens a sheet with the full summary or diff (side sheet from 768 px, bottom sheet below);
  - Approve and Reject buttons.

  Reject asks for an optional comment in a dialog. The bar never covers content: the page reserves padding for it. It sits above content and below dialogs, sheets and the open nav drawer. Under 768 px its buttons stack to full width. Keyboard: `A` approves and `R` opens Reject, except while focus is in a field or a dialog is open. The timeline's waiting step shows a short "Waiting for approval" marker instead of the decision.
- **Waiting signals:** while a gate is waiting, the run's tab title is "● Needs approval · Run <id8>". While any run in the workspace waits, every other page's title gets an "(N) ● Needs approval · " prefix, and "Runs" in the sidebar (and the mobile menu button) shows a count badge. Approvals are made on the console only: the runs list links waiting runs to it with "Review".
- **Live updates:** while a run executes, a live line at the end of the timeline says where it is and what it is doing ("writer · Reading `src/app.ts`…"). The page opens at the top; auto-scroll follows new content only once the user is at the bottom. Otherwise a "Jump to latest" pill appears.

### Interaction and accessibility

- WCAG 2.2 AA: visible focus rings, colour contrast ≥ 4.5:1, every action reachable by keyboard, `aria-live="polite"` for run status changes.
- Destructive actions (Reject, Disconnect, Remove key) ask for confirmation in a dialog. Success and failure of actions are shown with toasts.
- Motion is short (150–200 ms) and respects `prefers-reduced-motion`.

## Run history and rerun (API contract)

- `GET /runs`: run summaries, newest first, with cursor pagination and filters `status`, `template`, `repo`. Status, timings, PR URL and the waiting gate come from the run's events. They are kept in the `runs` row when events are written, so listing does not scan the log.
- `GET /runs/{id}`: one summary (the same shape as the list items, plus `input` and `failure_reason`).
- `POST /runs/{id}/rerun`: creates a **new** run with the same workflow spec, input, repo and workspace. It sets `rerun_of` and returns `CreateRunResponse`. The original run is never changed (the log is append-only). Resuming a failed run from its last completed node, which the checkpointer would allow, is a later option and not part of rerun.
- `POST /runs/{id}/cancel`: sets `runs.cancel_requested_at` and returns `202`. Only workers write events, so the worker running the run ends it (it checks every second); a queued run, or one waiting at a gate (queued again), is ended by the worker that claims it. The run ends `cancelled` with reason `cancelled by user`. An ended run answers `409`.
- **Delta volume:** the Claude adapter keeps streaming `text_delta`. The engine buffers deltas per node and writes at most one merged `text_delta` event every 250 ms. This keeps the log small and the stream live, while the client still merges what it receives.

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
| UI kit | shadcn/ui + Tailwind tokens (not MUI, Chakra or Ant) | We own the component code, it is accessible through Radix, it gives a modern, neutral enterprise look, and it themes through CSS variables. |
| Event display | Merge deltas on the client, buffer writes on the server (250 ms) | The append-only log and SSE replay stay unchanged. The UI shows messages, not chunks. |
| Rerun | A new run linked by `rerun_of` | The log stays immutable and the history stays truthful. Resuming from a checkpoint is a separate, later feature. |
