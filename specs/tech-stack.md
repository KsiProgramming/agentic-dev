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
- **Tokens:** every colour, radius and shadow is a semantic token (`--background`, `--foreground`, `--muted`, `--border`, `--primary`, `--overlay`, `--shadow-dock`, `--status-*`), defined for light and dark in `web/src/app/globals.css` and nowhere else. Components never use raw palette classes such as `bg-red-100`, arbitrary colours such as `bg-[#4f46e5]`, or hex, `rgb()` and `oklch()` values; ESLint rejects them (see "How the rules are enforced").
- **Type:** Inter for UI text, JetBrains Mono for ids, paths, code and JSON. Sizes come from the type scale tokens: `text-caption` 12 px (captions, table headers), `text-meta` 13 px (tables, metadata), `text-body` 14 px (body text, agent output), `text-section` 16 px (section titles), `text-page` 20 px (page titles), `text-stat` 24 px (stat values). Table headers are sentence case. Numbers use `tabular-nums`.
- **Density:** table rows are `h-row`, 40 px, or 32 px in compact mode. Compact mode is a toggle in the top bar, kept per browser (`localStorage`) and applied as the `compact` class on `<html>` before the first paint.
- **Theme:** light, dark and system, switched from the top bar.

### Layout

- **App shell:** a left sidebar (Runs, Templates, Settings, Audit log; workspace switcher at the top) and a top bar (breadcrumbs, theme, user). The sidebar collapses to icons from 1024 to 1279 px and becomes a drawer below 1024 px.
- **Breakpoints:** mobile-first. Designed and tested at 375, 768, 1024 and 1440 px. No horizontal page scroll at any width. Wide content (JSON, logs) scrolls inside its own box.
- **Width:** pages use the content width, up to 1600 px (`max-w-content`, set once by the shell). No page wraps itself in `mx-auto max-w-*`. Only reading text (page descriptions, agent output) is capped, at 72 characters (`max-w-prose`); code blocks and tables in it use the whole width.
- **Page header:** title, short description and primary actions on the right. On mobile the actions stack below the title.
- **Tables on desktop, cards on mobile:** a list keeps its columns at ≥ 768 px and turns into stacked cards below that.
- **States:** every data view has a skeleton loader, an empty state (icon, one sentence, primary action) and an error state (message plus Retry).

### Display values

Each kind of value has one component (`@/components/display`), used everywhere a value of that kind is shown. They are built on the formatters in `@/runs/summaries` and `@/runs/cost`, which are used directly only where the value must be a string (a placeholder, a toast, a page title).

| Value | Component | Shows |
|---|---|---|
| A moment | `RelativeTime` | Relative ("5 min ago") in a `<time dateTime>`, the exact date and time in a tooltip; `clock` shows the time of day for a log line |
| A duration | `Duration` | "2m 05s", "—" before it started |
| Time waited at gates | `WaitingTime` | "waiting 12m 04s" while the run waits, "waited 1h 00m" after; nothing if it never waited |
| When something runs out | `ExpiresIn` | "Expires in 2 d", "Expires in 3 h", "Expires in 12 min", then "Expired" (rounded down, ticking), the exact time in a tooltip |
| Money | `Money` | A cost from usage ("$0.042", "≥ $x" or "—" when unpriced, every count and the reason in a tooltip, "of $x" with a budget), or a plain amount as a cost or a `price` ("$3.00") |
| Tokens | `TokenCount` | "12.3K in", the exact counts in a tooltip |
| An id | `IdChip` | The short id (8 characters, mono), the full id in a tooltip; copies on click, or links with `href` |
| A figure | `StatTile` | Label, value in `text-stat`, one secondary line |

- **Time:** a run has three durations and the UI never mixes them:
  - *Active time*: steps executing. This is the "Duration" everywhere: `Duration` with the run's `active_ms`.
  - *Waiting time*: paused at gates, shown apart from it with `WaitingTime` ("2m 00s · waited 1h 00m"). A gate step's own time is waiting time.
  - *Wall clock*: start to end. Only in the tooltip of the start time (`RelativeTime` `detail`: "1h 02m start to end").
- **Locale and time zone:** dates and numbers use the display locale (`@/lib/locale`), today the browser's own locale and time zone (24-hour where the locale is). A workspace setting for them will pin it in that one module. Amounts are always USD, shown with "$". No component calls `toLocaleString()` or builds an `Intl` format itself. Unit tests and Playwright pin `en-US` and UTC.
- **Tooltips and focus:** a value with a tooltip takes keyboard focus to show it, except inside a list where every row has such values (`focusable={false}`): there the row's link and actions are its tab stops.

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
- **Timeline (default tab):** the run reads top to bottom on a vertical rail. Each node hangs off it by a status icon (with a screen-reader label) and shows its duration; a finished node has no badge, and only states that need attention say so in words ("Needs approval", "Failed"). Map items (named by their path), parallel branches (named by their id) and loop iterations are nested on their own rail. Inside a step:
  - Streamed `text_delta` events are **merged on the client** into one growing message per agent turn. The `message` event replaces the merged text when it arrives. A message is rendered as Markdown with raw HTML and images dropped, so payloads stay data.
  - Each tool call is one quiet line with an icon, a verb and its target ("Read `src/app.ts`"); opening it shows its arguments and result (JSON pretty-printed, collapsed after 2 levels, copyable). Consecutive reads, listings and searches collapse into one summary line ("Read 12 files, listed 3 folders"). Calls that change something (writes, commits, pull requests) and failed calls stand on their own line with a preview of their first lines. Only running and failed calls get a status icon.
  - Usage and cost appear as a quiet footer line ("12.3K in · 2.1K out · $0.042"); a map or loop node shows the total of its items. The header shows the run's total. A cost with unpriced usage shows "—" (or "≥ $x") and says why in a tooltip.
- **Raw events tab:** the event table, with filters by type and node. Consecutive chunks of one message are folded into one row (expandable to the chunks). It is kept for debugging and audit.
- **Graph tab:** the run's workflow drawn read-only with React Flow, from the spec on `GET /runs/{id}` (`spec`), top to bottom in run order:
  - Sequences are not drawn, only their steps. A map or a loop is a box holding its body, its header saying how far it got ("2 of 3 items · 1 failed", "Iteration 2 of 5"). A parallel is a box holding its branches side by side, top aligned ("2 of 3 branches · any · 1 cancelled"). A reduce is linked to its map ("reduces"; dashed when it is not the step right after it).
  - Each node shows a type icon, its id (mono), one line on what it does (role, tool, gate title) and its status as icon + label; "Not started" until the run reaches it. A node run several times (in a map or a loop) shows what needs attention first: failed, waiting, running, cancelled, then done. Running, waiting and failed tint the border.
  - Status comes from the same timeline as the Timeline tab. The layout is computed once per spec; events only change the nodes' states.
  - Nothing moves, connects or is deleted; the graph pans and zooms inside its own box (`min(70svh, 720px)`), so the page never scrolls sideways.
  - Each node is a button (one tab stop, Enter or Space opens it) with an accessible name ("worker, agent, Done"). It opens a sheet (side sheet 480 px from 768 px, bottom sheet below) with the timeline's step view; a node inside a map or a loop shows one entry per item or iteration. The dock's `A` / `R` shortcuts work while a node has focus, not while the sheet is open.
- **Approval dock:** while a gate is waiting, a bar is fixed to the bottom of the viewport with:
  - the gate title, and when it expires (`ExpiresIn`, when the gate has an expiry);
  - a one-line summary: the gate's prompt, else the first line of its artifact;
  - "Review details", which opens a sheet with the full summary or diff (side sheet from 768 px, bottom sheet below);
  - Approve and Reject buttons.

  Reject asks for an optional comment in a dialog. The bar never covers content: the page reserves padding for it. It sits above content and below dialogs, sheets and the open nav drawer. Under 768 px its buttons stack to full width. Keyboard: `A` approves and `R` opens Reject, except while focus is in a field or a dialog is open. The timeline's waiting step shows a short "Waiting for approval" marker instead of the decision.
- **Review sheet (a gate with changes):** "Review details" opens a wide sheet with the writers' changed files instead of the artifact.
  - From 1024 px it is a side sheet (`min(1100px, 92vw)`) with the file list on the left and the diff on the right. Below 1024 px it is a full-height bottom sheet with a file picker above the diff.
  - Each file shows its status as icon + label (Added, Modified, Deleted, Renamed), "Edited" once changed, and why it is read-only (binary, too large, past the limit, deleted, renamed).
  - The diff is a Monaco `DiffEditor`, bundled and loaded only when the sheet opens: side by side from 1024 px, inline below. The original side is read-only; the changed side is editable for editable files. Its theme follows the app's.
  - Each edited file has "Discard edits". With edits, Approve reads "Approve with N edits" (dock and sheet footer), and Reject says the edits will be dropped. `Esc` closes the sheet and keeps the edits; leaving the page with edits asks first.
  - The decided step reads "Approved with edits to N files", and each edited file opens as a read-only diff.
- **Waiting signals:** while a gate is waiting, the run's tab title is "● Needs approval · Run <id8>". While any run in the workspace waits, every other page's title gets an "(N) ● Needs approval · " prefix, and "Runs" in the sidebar (and the mobile menu button) shows a count badge. Approvals are made on the console only: the runs list links waiting runs to it with "Review". A gate past its `expires_at` is not counted anywhere, even in the seconds before the worker cancels its run.
- **Expired runs:** a run whose gate expired is `cancelled`, not a status of its own. Its badge has Cancelled's grey and icon with the label "Expired" (runs list, console header), and the console shows the reason above the timeline in a neutral alert ("Approval expired: nobody approved or rejected the gate before its time to live ran out"). A run its user cancelled stays "Cancelled".
- **Live updates:** while a run executes, a live line at the end of the timeline says where it is and what it is doing ("writer · Reading `src/app.ts`…"). The page opens at the top; auto-scroll follows new content only once the user is at the bottom. Otherwise a "Jump to latest" pill appears.

### Audit log

- **Page (`/audit`):** the workspace's activity, newest first: page header (title, one-line description, Refresh), filters, then the list. It does not update live; Refresh reloads it.
- **List:** a table from 768 px with Time, Action, Actor, Run and Details; stacked cards below. Time is relative with the exact time in a tooltip (`tabular-nums`). Action is icon + label. Actor is "System" for the worker, else "—" with a tooltip saying names come with sign-in. Run is the run's id8 in mono, linking to its console, with the template and repo under it.
- **Details:** one line of text per action, built by a formatter from `details` ("Approved `approve` with edits to 2 files · "looks good""). Never rendered as HTML or Markdown. An unknown action shows its name.
- **Filters:** category (Runs, Approvals, Settings), run id and a date range, kept in the URL. "Load more" fetches the next page.

### Interaction and accessibility

- WCAG 2.2 AA: visible focus rings, colour contrast ≥ 4.5:1, every action reachable by keyboard, `aria-live="polite"` for run status changes.
- Destructive actions (Reject, Disconnect, Remove key) ask for confirmation in a dialog. Success and failure of actions are shown with toasts.
- Motion is short (150–200 ms) and respects `prefers-reduced-motion`.

### UI v2 (Milestone 11)

Planned changes to the rules above, from a review of the shipped screens. Until a phase ships, the rules above stay in force; the phase's PR moves its part into them and removes it from here. Foundations (11.1) shipped: brand accent, type scale, density, width and display values are in Look, Layout and Display values above. Time (11.2) shipped: it is in Display values above and in the run history contract below. Approval expiry (11.3) shipped: it is in Display values and Run console above, and in the run history, gate review, audit log and security sections below.

- **Runs list (11.4)**, replacing "Needs approval first" from 2.4:
  - Saved views as tabs, each with a count: All, Running, Needs approval, Failed. The view and filters live in the URL. Nothing is pinned above the list.
  - Columns: Status, Run (workflow name; under it the short id and the trigger), Repository (with the branch under it), Started, Duration (active, plus the waiting chip), Cost, Pull request, actions. A waiting row's status badge links to its review, replacing the separate "Review" button.
  - Rows are grouped under sticky date headers (Today, Yesterday, This week, Earlier).
  - Runs started by e2e tests and demos run in their own workspace, never in the default one.
- **Inbox (11.5)**, replacing "Approvals are made on the console only" from 2.6:
  - `/inbox` lists the gates waiting on the user, oldest first, with the workflow, repo, waiting time and time left before expiry.
  - Selecting one shows its review beside the list (below it under 1024 px): what approving does (target repo, branch into base), the summary or the changed files with the same diff view as the review sheet, the run's cost and active time so far, and Approve, Reject (with comment) and Open run. `A` / `R` work as in the dock.
  - The sidebar gets an "Inbox" entry first; the waiting count moves there from "Runs". The console's approval dock is unchanged.
- **Run console (11.6)**, replacing the Header and the tab layout of the Run console section:
  - Header: workflow name, status badge, `IdChip`; under it repo › branch, who started it and when. Actions on the right: the pull request as the primary action once opened, Rerun, Cancel while live, and a "⋯" menu (copy link, download events).
  - Stat tiles under the header: Active time (waited time under it), Cost (against the budget when one is set), Tokens (in, out and cache in the tooltip), Steps (done of total), Output (PR number and state).
  - A banner under the tiles when the run failed (failing step, reason, "Go to step") or waits at a gate (title, time left, link to the decision).
  - Body in two panes from 1280 px, stacked below: on the left the step list (status icon, type icon, name, one line on what it did, duration and cost; map items and loop iterations nested), switchable to the Graph; on the right the selected step with tabs Output (default), Activity (the tool calls), Input, Usage and Events. The running step is selected while the run is live, unless the user picked another.
  - Output: the agent's final message as Markdown, capped at about 480 px with "Show full output". Files the step wrote are cards (path, kind) that open the file.
  - Raw events: one 32 px row per event (number, time from start, type, step, one-line summary). The payload opens in a side drawer in `JsonView`; table cells never hold JSON.
- **Shell and settings (11.7):**
  - Command palette on `⌘K` / `Ctrl+K`: jump to a run by id, PR number or workflow; New run; Approve (on a waiting run); Toggle theme.
  - The theme moves into a user menu at the bottom of the sidebar.
  - Settings is split into sub-pages with a secondary nav: Integrations (Claude, GitHub), Models and pricing, Limits and budgets. Each sub-page is a short stack of cards.
  - The pricing table fits its card: Model, Input, Output, Cache write and Cache read, with the two cache-write prices stacked in one cell.
  - The limits form: each field with its unit and the platform maximum as help text; a sticky Save / Discard bar appears only once the form has changes.
- **Agent activity (11.8)**, replacing the tool-call grouping in "Timeline" and shown in the step's Output and Activity from 11.6. An agent's work reads the way a chat with Claude does: the work folds away, the answer stays.
  - **Agent turn = work block + answer.** Everything an agent does before its answer (tool calls, short notes, reasoning) is one collapsible work block. The answer (the turn's final message) sits below it, always open. A turn with no tool calls is just its answer.
  - **Header of a live block:** a spinner, the current step's title ("Reading the frontend config") and an elapsed timer that ticks ("1m 06s"). The block is open while live and follows new rows only when the user is at its bottom (same rule as the timeline).
  - **Header of a finished block:** a chevron, the summary of what was done ("Listed 3 folders, read 11 files, ran 1 search"), then "15 tool calls · 8s" on the right. Closed by default; a block with a failed call opens and shows the failure.
  - **Rows inside, in order:**
    - a *tool row*: the call's intent as its title ("Read the frontend config and agent rules"), what it touched as a quiet second part (the existing `describeTool` line: "Read `web/package.json`"), its duration on the right, a chevron to arguments and result. Consecutive reads, listings and searches with no intent fold into one summary row, as today.
    - a *note row*: text the agent wrote between calls, one or two quiet lines, not a message block.
    - a *reasoning row*, only when the provider streams it: the first line of the reasoning in muted italic, the rest on expand. Never open by default.
    - Writes, commits, pull requests and failed calls keep their preview under the row, as today.
  - **Where intents come from:** the platform's tools (`repo.*`, `github.*`) accept an optional `description` argument ("why this call, in under 10 words"); the agent instructions ask for it. Without one, the row's title is the `describeTool` line. The description is agent output: shown as plain text, never as Markdown or HTML (mission principle 5).
  - **Reasoning events:** an adapter that receives reasoning from its provider (Claude extended thinking) logs it as `reasoning_delta` events, buffered like `text_delta`. An adapter that does not simply logs none, and the UI shows no reasoning rows.
  - **Groups across a map:** each map item has its own work blocks under the item, as today; the map's header sums its items ("2 items · 31 tool calls · 21s").
  - **Accessibility:** a block's header is a button with `aria-expanded`; its name reads the summary and count ("Listed 3 folders, read 11 files, 15 tool calls, 8 seconds"). The ticking timer is not announced; the live line keeps `aria-live="polite"`.

#### How the rules are enforced

A rule an agent can break without noticing will be broken. So each one is either checked by a tool or written in [`CLAUDE.md`](../CLAUDE.md), which coding agents read before every task:

- ESLint (`agentic-ui/no-raw-colors`, a local rule in `web/eslint/`) rejects palette colour classes (`bg-red-100`, `text-indigo-600`, `bg-black/10`), arbitrary colour values (`bg-[#…]`, `text-[oklch(…)]`) and hex, `rgb()` and `oklch()` literals in `web/src`, outside tests. `pnpm lint` fails on them.
- axe and the layout screenshots in `e2e/` run in CI at 375, 768 and 1440 px.
- `CLAUDE.md` lists the shared components to use for each kind of value, so a new screen is assembled from them rather than restyled.

## Run history and rerun (API contract)

- `GET /runs`: run summaries, newest first, with cursor pagination and filters `status`, `template`, `repo`. Status, timings, PR URL and the waiting gate come from the run's events. They are kept in the `runs` row when events are written, so listing does not scan the log.
- `GET /runs/{id}`: one summary (the same shape as the list items, plus `input` and `failure_reason`).
- **Run time (11.2):** each summary has `active_ms` (time executing; `null` until the run started, and for runs that ended before 11.2) and `waiting_ms` (time paused at gates), each counting its open stretch up to `measured_at`, from which a client keeps a running run's active time or a waiting run's waiting time growing. Active runs from `run_started` or `run_resumed` to `gate_waiting` or the end; waiting from `gate_waiting` to `run_resumed` or the end (a cancel while waiting). An attempt that was cut off counts until its last event, and the gap before the next attempt is neither. The sink keeps both in the `runs` row (`active_ms`, `waiting_ms` and the open stretch's `active_since` or `waiting_since`) as it writes the boundary events. `duration_ms` (wall clock) is deprecated.
- `POST /runs/{id}/rerun`: creates a **new** run with the same workflow spec, input, repo and workspace. It sets `rerun_of` and returns `CreateRunResponse`. The original run is never changed (the log is append-only). Resuming a failed run from its last completed node, which the checkpointer would allow, is a later option and not part of rerun.
- `POST /runs/{id}/cancel`: sets `runs.cancel_requested_at` and returns `202`. Only workers write events, so the worker running the run ends it (it checks every second); a queued run, or one waiting at a gate (queued again), is ended by the worker that claims it. The run ends `cancelled` with reason `cancelled by user`. An ended run answers `409`.
- **Approval expiry (11.3):** a run waiting past its gate's expiry is cancelled the same way, by the workers rather than the API.
  - The sink keeps the waiting gate's `expires_at` in `runs.gate_expires_at` (and in `waiting_gate`), cleared on resume, decision and end.
  - Every worker runs `agentic_store.expire_gates` every `GATE_SWEEP_S` (default 30 s): each waiting run past its expiry with no decision recorded is locked (`SKIP LOCKED`), set `queued` with `cancel_requested_at` and `cancel_reason = "Approval expired"`, given a `gate.expired` audit entry, and enqueued. The worker that claims it removes its sandbox and writes `run_cancelled` `{reason: "Approval expired", expired: true}`.
  - `runs.cancel_reason` keeps the first reason a run was cancelled for (`cancelled by user` from `POST /runs/{id}/cancel`), and the sink sets it from `run_cancelled`'s `reason`.
  - Each summary has `cancel_reason` (for a cancelled run, else `null`) and `expired` (`true` when that reason is "Approval expired"); `waiting_gate` has `expires_at`.
  - Gates already waiting when 11.3 shipped were given 72 h from when they paused (Alembic `0021_approval_expiry`), so the first sweep expired the stale ones.
- **Delta volume:** the Claude adapter keeps streaming `text_delta`. The engine buffers deltas per node and writes at most one merged `text_delta` event every 250 ms. This keeps the log small and the stream live, while the client still merges what it receives.

## Workflow validation (API contract)

- `POST /workflows/{id}/validate` checks a spec without running it.
  - Body: `workflow` (raw JSON), optional `workspace_id` and `budget_usd`.
  - Answer: `200 {valid, issues, policy}`. An invalid spec is a normal answer, not an error. `404` means an unknown workspace, and `422` a malformed request.
  - It stores nothing and needs no connection. Until 5.1 stores workflows, `{id}` must equal the spec's `id` (`id_mismatch` otherwise).
- One validator, `agentic_engine.spec.validate_workflow`, serves the endpoint, the spec model and `POST /runs`.
  - Each issue has a stable `code`, the spec `path` (`root.steps[1].body`), the `node_id` to fix and a `message`. Policy issues also have `limit`, `value` and `observed`.
  - Codes: `schema`, `id_mismatch`, `duplicate_node_id`, `invalid_expression`, `not_allowed_in_loop`, `not_allowed_in_map`, `not_allowed_in_parallel`, `reference`, `publish_not_tool_node`, `publish_without_gate`, `create_not_tool_node`, `create_without_gate`, `create_not_first`, `unknown_tool`, `policy_limit`, `budget_unpriced_model`.
  - A spec off the schema gets only `schema` issues. Otherwise every issue is listed, in run order.
- Tool names must be platform tools (`PLATFORM_TOOLS`); the tool servers register exactly these, and a test keeps them in sync. `POST /runs` refuses an unknown one with `422`.
- `POST /runs` and rerun put the same issues in their `policy_limits` detail (`issues`), next to `errors`.

## Gate review (API contract)

- A gate shows the files changed on the branches of the writer nodes that completed before it, in its `gate_waiting` payload: `changes`, next to `title`, `prompt`, `artifact`, `ttl_s` (how long it waits: the gate's own `ttl_s`, else the run's `approval_ttl_s`) and `expires_at` (ISO, the pause plus `ttl_s`).
  - Each entry: `node_id` (the writer), `path`, `old_path` (renames), `status` (`added`, `modified`, `deleted`, `renamed`), `editable`, `reason`, `before` and `after`.
  - Only an editable file has contents: `before` at the branch's base (the clone's `HEAD`; `null` for an added file) and `after` at its tip. A file is editable when it is added or modified, UTF-8 text with no NUL byte, and at most 256 KB on either side.
  - Other files are listed with a `reason`: `binary`, `too_large`, `deleted`, `renamed`, or `over_limit` past the first 50 files or 512 KB of text.
  - If the changes cannot be read, the gate pauses anyway with `changes: []` and `changes_error`.
  - The worker reads them through a `GateReview` (`agentic_engine.gate`) over the run's sandbox, so the engine never runs git.
- `POST /runs/{id}/approvals` takes `edits: [{node_id, path, content}]` on an approval.
  - Each must name an editable file of the gate's last `gate_waiting`. An edit equal to `after` is dropped.
  - `422` with `detail: {code, message, path}`: `edit_not_allowed`, `edits_with_reject`, `edit_too_large` (a file over 256 KB, or edits over 512 KB in all), `duplicate_edit`.
  - The edits are stored with the approval (`approvals.edits`), and the answer says how many files they change (`edited_files`).
  - A decision on a gate past its `expires_at` answers `409`, even before the sweep has cancelled the run: what the dock says expired is expired.
- On approve, the gate commits the edits in each writer's worktree before it completes: one commit per writer, `Edit at gate <id>` with an `Edited-by: reviewer` trailer, by the agent identity, of only the edited files. `gate_decided` adds `edits` and `commits` (each writer's new tip).
  - It is idempotent: a gate that runs again after a crash finds the files already edited and makes no second commit.
  - Edits that cannot be committed fail the gate node, and so the run. A run is never approved without its edits.

## New repos (API contract)

- `POST /runs` (not rerun) takes `new_repo` instead of `repo`: `name`, `private` (default `true`), `description`, `gitignore`, `license`.
  - The repo is created in the organisation of the workspace's GitHub App installation. Installation tokens cannot create repos on a personal account, so those get `409` `personal_account` (and `no_connection`, `installation_gone` as for repos). A name already taken gets `409` `repo_exists` before the run exists.
  - The API puts a gate (`approve_repo`) and a `github.createRepo` tool node (`create_repo`) before the workflow's steps (`agentic_engine.templates.wrap_with_create_repo`), and sets the run's `repo` to the new repo's URL.
- Spec rules: `github.createRepo` is called by a tool node only, at most once, as a step of the root sequence, after a gate, and before any node that uses `repo.*` or `github.*`.
- `github.createRepo` creates the repo with GitHub's `auto_init` (one commit: a README, and the `.gitignore` and license asked for) and logs `repo_created` (`full_name`, `url`, `default_branch`, `private`, `created`). On a retry it takes over an existing repo of that name only if it was created after the run.
- After it, a `<id>.ready` step interrupts the graph with no event: the attempt ends `suspended`, and the worker starts the next one at once, which clones the repo. Until `repo_created`, a run's attempts have no sandbox and only the `github` server (without `openPR`).
- A run that created its repo is not rerun (`409` `repo_exists`).
- `GET /workspaces/{id}/repos/new-repo-options`: `{owner, can_create, reason, message, gitignore_templates, licenses}`.

## Audit log (API contract)

- `audit_events` is append-only: a trigger refuses `UPDATE` and `DELETE`. Columns: `id`, `workspace_id`, `at`, `action`, `actor_type` (`user` | `system`), `actor_id` (`NULL` until users exist), `run_id`, `node_id`, `details` (JSON).
- Each row is written in the transaction of the change it records, so a row exists if and only if the change was committed:

  | Action | Written by | `details` |
  |---|---|---|
  | `run.created` | `create_run` | `template_id`, `repo_url`, `budget_usd` |
  | `run.rerun` | `create_rerun` | `rerun_of`, `budget_usd` |
  | `run.cancel_requested` | `request_cancel`, first request only | `status` (before) |
  | `run.ended` | the event sink, on the run's end event; actor `system` | `status`, `failure_reason`, `cancel_reason`, `pr_url`, `estimated_usd` |
  | `repo.created` | the event sink, on the run's first `repo_created`; actor `system` | `full_name`, `private` |
  | `gate.approved`, `gate.rejected` | `record_approval` | `comment`, `edited_files`, `edited_paths` |
  | `gate.expired` | `expire_gates`, in the worker's sweep; actor `system` | `title`, `expires_at` |
  | `connection.added`, `connection.removed` | the connection writers | `provider`, `key_hint` or `account_login` |
  | `policy.updated` | `replace_policy_overrides` | `before`, `after` (the workspace's overrides) |
  | `pricing.updated` | `replace_price_overrides` | `added`, `changed`, `removed` (model names) |

- `details` never holds file contents or secrets: edited paths, not edits; key hints, not keys. USD amounts are decimal strings.
- Runs and approvals made before the table existed are backfilled by its migration. Older settings changes are not recorded.
- `GET /workspaces/{id}/audit`: `{items, next_cursor}`, newest first, with `cursor`, `limit` (1–200, default 50), `action` (repeatable), `run_id`, `since` and `until`. Each item: `id`, `at`, `action`, `actor {type, id}`, `run_id`, `node_id`, `details`, and `run {template_id, repo_url, status}` when it has a run. `404` is an unknown workspace, `422` a bad cursor or filter.

## Security & secrets

- Secrets are encrypted with a KMS key per workspace (cloud KMS in production; a local key file in dev). They never appear in logs or agent context.
- Policy limits are enforced in the engine at validation time and at runtime:
  - **Budget (USD): optional.** No default cap. If set, it is a hard stop at 100%. If unset, the run continues and cost is still tracked.
    - A workspace may set a default budget (the "Budget" field of the "Run limits" card), and a run may set its own when it starts (`budget_usd` on `POST /runs` and rerun), which replaces it. It has no platform ceiling. From $0.01 to $1,000,000.
    - The run's budget is frozen in `runs.policy` with its other limits. With a budget, every agent's model must have a price in the workspace, or the run is refused with `422`: a cap that cannot be measured is not a cap.
    - The engine meters it: the worker seeds a meter with the run's spend so far (`runs.estimated_usd`, so earlier attempts and the time before a gate count), and each `usage` event adds its `estimated_usd`. Once the spend reaches the budget, or a usage has no price, the running nodes end `node_cancelled` and the run ends like any other limit (`policy_limit_exceeded` with `limit: "budget_usd"` and USD amounts as decimal strings). The call that crossed the budget is already paid, so it is counted in full.
  - Agents alive 8, agents spawned 40, nesting depth 2, loop iterations 5, wall time 2 h, approval time to live 72 h (`approval_ttl_s`), gates before push/PR/repo creation/Jira status change.
  - These defaults (`agentic_engine.policy.PLATFORM_POLICY`) are also the ceilings. A workspace may lower each one (`GET`/`PUT /workspaces/{id}/policy`, the "Run limits" card in Settings), never raise it.
  - A run gets the workspace's effective limits when it is created (`runs.policy`) and keeps them, resumes included. A rerun gets the limits as they are then.
  - Checked before the run (`POST /runs` and rerun answer `422`): loop `max_iterations`, map `max_concurrency` and a parallel's branches against agents alive, nesting depth (loops, maps and parallels), and a gate's `ttl_s` against the approval time to live. Checked while it runs: agents spawned (every agent start, a map's items all at once when it starts) and agents alive (extra agents wait for a slot). The worker checks wall time, which counts only time spent executing, not time waiting at a gate: the run's active time (above), read from its `runs` row.
  - A run over a limit ends `failed`: a `policy_limit_exceeded` event (`limit`, `value`, `observed`), then the failure with a readable reason.

## Observability

- OpenTelemetry traces across API, engine nodes and tool calls.
- Cost and token metrics per node, run, user and workspace, derived from usage events.
- **Pricing:**
  - The adapter prices each provider call when it emits its `usage` event, from the workspace's price table: list prices in `agentic_runtime.pricing` (dated by `PRICES_AS_OF`, checked by hand against the provider's pricing page) with the workspace's overrides on top (`GET`/`PUT /workspaces/{id}/pricing`).
  - Cache reads and writes are counted and priced apart from input.
  - The logged `estimated_usd` never changes, and the `runs` row keeps the run's totals.
  - A model with no price logs its tokens with no cost, and the run's cost is then marked incomplete.
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
| Cost | Priced by the adapter when usage is logged, never recomputed | The append-only log stays truthful, a budget stop (3.3) can always be explained, and changing a price never rewrites past runs. |
| Policy limits | Platform ceilings a workspace may only lower, frozen on each run when it is created | Safe by construction (mission principle 2), and a stop can always be explained by the limits the run was given. |
| Budget | A workspace default a run may replace, metered in the engine on every priced usage | Stops right after the call that crosses it, across parallel agents, and survives restarts because the meter starts from the stored spend. |
| Run graph | Drawn from the run's stored spec with a hand-written tree layout; nodes are buttons | One spec, many views: nodes that have not run yet are shown, and graph and timeline read the same status. The spec is a tree, so no layout library is needed yet. A parallel's branches sit side by side inside its box with no edge leaving it, so 4.1 kept the hand-written layout; ELK (`elkjs`) replaces it once edges cross boxes (4.6 `router`), as Dagre mislays sub-flows linked to outside nodes. A button per node gives one tab stop and native Enter/Space, which React Flow's own node focus (select on Enter) does not; nodes keep `pointer-events: all`, which React Flow turns off on unselectable nodes. |
| Validation | `200` with structured issues from one engine validator | The canvas and the Architect read issues as data, not as failures. One validator means they never disagree with what a run accepts. |
| Gate edits | The writers' changed files in `gate_waiting`, edits committed by the gate node | The PR is pushed from the writers' branches, so editing them is what changes it. The log records what the approver saw and changed. Committing inside the gate node checkpoints it with the gate, and the next node (`openPR`) needs no change. |
| New repos | Organisation repos only, created by a gated `github.createRepo` node with GitHub's `auto_init`; the attempt then ends `suspended` and the next one clones the repo | Installation tokens can create organisation repos but not personal ones, and there are no user tokens yet. A scaffold made by GitHub needs no push from the sandbox. Continuing in a new attempt reuses the clone-at-start path, so the sandbox, the tools and gate review do not change. |
| Parallel | One `Send` per branch and a join node; the join is decided as soon as its outcome is known and the branches still running are cancelled | It reuses the map's fan-out and per-task checkpoints. Deciding early spends no tokens on branches that cannot change the outcome. Cancelling is only an optimisation inside one attempt: the join decides from the checkpointed outcomes, so a resumed run joins correctly. Branches hold no gates or writers until several gates can wait at once and parallel writers have an integration branch (6.3). |
| Audit log | An append-only `audit_events` table written in each change's transaction | It records settings changes no other table keeps, and its rows never change, unlike `runs`. Writing it with the change means no row is missing or invented. Who acted is a nullable `actor_id` until users exist. |
| Run durations (11.2) | Active time, waiting time and wall clock kept apart; "Duration" means active time | A run that waited a weekend for approval is not a 60-hour run. Mixing the two makes every duration in the product untrustworthy. |
| Run time projection (11.2) | Active and waiting time kept on the `runs` row by the event sink, with the open stretch's start; not durations in event payloads, not computed from the log on read | The same pattern as the other summary columns: listing never scans the log and no event changes shape. The wall-time limit reads the same columns, so the limit and the UI share one definition of active time. Only runs live at the migration are backfilled. |
| Approval expiry (11.3) | A gate's time to live cancels the run with a reason; no new run status | Stale gates stop shouting in every waiting count, and the six statuses (and every filter and badge built on them) stay as they are. The reason keeps the history truthful. |
| Expiry mechanics (11.3) | The time to live is a policy limit (72 h ceiling) with an optional shorter `ttl_s` per gate; `expires_at` is fixed in `gate_waiting`; a sweep in every worker turns expiry into a cancel request (not lazy expiry on read) | The same model as the other limits, so a stop is explained by the limits the run was given, and a later policy change never moves a gate already waiting. Only workers write events, and the cancel path already removes the sandbox and writes the end; a run nobody opens still expires. |
| Where approvals happen (11.5) | An Inbox beside the console's dock, both on the same review components | An approver works through what waits on them in one place; the dock still serves someone already watching the run. One set of review components means the two never disagree. |
| UI rules for agents (11.1) | Rules in `CLAUDE.md`, backed by ESLint and the e2e layout and axe checks | Coding agents follow what they read at the start of every task and what CI rejects. A prompt pasted once drifts by the next session. |
| Specs govern the work | `specs/mission.md`, `specs/roadmap.md` and `specs/tech-stack.md` are the repo's constitution; `CLAUDE.md` points agents to them and repeats only the rules they must not miss | An agent or a person reads one place to know what to build and how. A decision kept only in code, a chat or `CLAUDE.md` is lost by the next task, so every decision, phase and rule change lands in these files first, in the same PR. |
| Roadmap order | A milestone added later takes the next free number and is listed where it is worked; a "Next up" line names the milestone to plan next | Phase numbers are quoted in spec folders, the changelog and code comments. Renumbering left stale references once (see `TODO.md`), so numbers never change and order lives in the list instead. |
| Brand accent (11.1) | Indigo stays (not a near-black "ink" primary) | It is already tuned for contrast in light and dark, and the review's problems were information design, not the accent. Changing it later is a token change in `globals.css` only. |
| Display locale (11.1) | The browser's locale and time zone, behind one module (`@/lib/locale`) | Locale-aware dates and numbers now with no API change; a workspace `locale` / `time_zone` setting later pins them in that module and nowhere else. |
| Colour lint (11.1) | A small local ESLint rule over string and template literals | No maintained rule covers Tailwind v4 palette classes, arbitrary values and colour literals together; a regex rule is short and tested with `RuleTester`. |
| Tool intent (11.8) | An optional `description` argument on the platform's tools, written by the agent | The console can say why a call was made, not only what it did, at no extra model call. Optional, so a provider or agent that leaves it out still works and falls back to the mechanical line. |
