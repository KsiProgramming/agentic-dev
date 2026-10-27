# Run console v2

Roadmap phase: 2.5
Branch: plan/2.5-run-console-v2

## Context
`/runs/{id}` was still the 0.8 debug view: one table row per event, so a docs run showed hundreds of `text_delta` rows and the tool calls were raw payloads. The Runs page (2.4) links every run here, so this is the page users land on. This phase turns it into the run console described in [tech-stack.md → Run console](../tech-stack.md#run-console): a header, a timeline that reads as a story, and the raw log one tab away.

Depends on 2.1 (tokens, `StatusBadge`, states), 2.2 (shell, `PageHeader`), 2.3 (`GET /runs/{id}` summary) and 2.4 (TanStack Query). All are done. It does not depend on 1.12, which is still unplanned. It unblocks 2.6 (approval dock sits on this page, Rerun action in this header), 3.1 (cost per node in the usage footer) and 3.5 (Graph tab opens the node detail from here).

Principles and choices that apply:
- **Mission 8, Enterprise-grade, calm UI:** runs read as a story (nodes, messages, tool calls); the raw event log is one click away, not the default.
- **Mission 6, Transparency:** every agent action and tool call stays visible; nothing is hidden, only grouped.
- **Mission 5, content is data:** agent messages render as Markdown with raw HTML dropped; tool output is shown as text/JSON, never interpreted.
- **Mission 3, humans approve irreversible actions:** Cancel only stops the run; it never pushes or opens anything.
- **Tech stack → Event display:** merge deltas on the client *and* buffer writes on the server (250 ms). The append-only log and SSE replay stay unchanged.
- **Tech stack → Frontend:** `react-markdown` for messages, a collapsible JSON viewer, TanStack Query, `lucide-react`, JetBrains Mono for JSON and ids.

## Scope
### In scope
- **Timeline model (pure, client):** a reducer from the ordered `RunEvent[]` to a timeline:
  - One step per node in run order (first `node_started` / `gate_waiting`), with status and duration from its lifecycle events. Loop iterations are separate entries of the step ("Iteration 2").
  - Map items nested under their map node (`map_item_started` / `map_item_completed`, and the `item` tag on child events), each with its own status.
  - Inside a step, a list of **turns**. Consecutive `text_delta` events form one growing message; a `tool_call` closes the current message. The `message` event replaces the merged text of the last turn (or adds one if none is open).
  - `tool_call` and its `tool_result` (same `call_id`) form one tool turn; a result that has not arrived yet shows the call as running.
  - `usage` events summed per step into a footer (input/output tokens; USD is 3.1).
  - Node errors (`node_failed` payload, agent `failed`) shown inline in the step.
- **Header** (`PageHeader`): status badge (live), workflow name, repo (`owner/name`, mono) and branch, started time, live duration, PR link once `pr_opened` arrives. Actions: **Cancel** (only while queued, running or waiting; confirm dialog) and **Copy run id**. Static facts come from `GET /runs/{id}`; status, duration and PR stay live from the run's own event stream, and the summary is refetched when the stream moves on.
- **Timeline rail** (after a review against Claude Code's transcript view): steps, map items and iterations hang off a vertical line by a status icon (check, cross, spinner, pause), with a screen-reader label so status is never colour alone. Messages get a quiet dot, tool groups a small status dot. A done step has no badge; only waiting ("Needs approval"), failed, running and cancelled say so in words.
- **Message rendering:** `react-markdown` + `remark-gfm`. Raw HTML in agent text (e.g. `<!-- module: src -->` markers) is dropped, never rendered; images are dropped (an image URL would make the browser fetch it); links open in a new tab with `rel="noreferrer"`; a caret while the turn is still streaming.
- **Tool calls (user feedback: a card per call was too heavy):**
  - Each call is one quiet line with an icon, a verb and its target: "Read `src/app.ts`", "Listed `src`", "Searched for `Item`", "Wrote `docs/a.md`", "Committed `docs: …`". A call in flight says what it is doing ("Reading …"); only running and failed calls get a status icon. Opening a line shows its arguments and result (JSON pretty-printed, collapsed after 2 levels, copyable; plain text otherwise).
  - Consecutive quiet calls (reads, listings, searches) collapse into one summary line: "Read 12 files, listed 3 folders, ran 1 search · 16 tool calls · 8s". While one runs, the line says what is happening.
  - Calls that change something (file writes, commits, pull requests) and failed calls stand on their own line with an inline preview of their first 4 lines ("+111 more lines").
  - Unknown tools read "Called `<name>`" with their first string argument.
- **Map items** are named by their `path` (or `name`, `id`), with their `kind`, instead of raw JSON; an item whose body is one step is not headed twice.
- **One message, one row (both views):** chunks of the same message are never shown one per row. On the Timeline they form one message block that reads as complete paragraphs. On Raw events, consecutive `text_delta` events of the same node and map item are folded into **one row** showing the joined text, the `seq` range and the chunk count ("`text_delta` × 37"); the row expands to list the individual chunks. A different event or a different node/item ends the fold.
- **Tabs:** Timeline (default) and Raw events. Raw events is the event table, with deltas folded as above, plus filters by type and by node. The tab is kept in the URL (`?tab=raw`).
- **Live behaviour:**
  - A live line at the end of a running run's timeline says where it is and what it is doing ("writer · Reading `src/app.ts`…", "Writing", "Thinking"), with how many steps run at once during a map.
  - The page opens at the top. Auto-scroll follows new content only once the user has scrolled to the bottom; otherwise a "Jump to latest" pill appears. The replay of stored events when the page opens (its first 1.5 s) neither scrolls nor shows the pill.
  - `aria-live="polite"` announces run status changes.
- **Gate panel:** the existing inline `GatePanel` stays, rendered in the waiting gate's step. The sticky dock is 2.6.
- **Server delta buffer (engine):** a `DeltaBuffer` per node (and per map item) around `on_event` in `_run_step`. The first chunk of a burst is written at once; the chunks that follow within 250 ms are joined into one `text_delta`, written by a timer or before any other event of that node (tool call, message, usage, node end) and on cancellation, so order and the concatenated text are unchanged.
- **Cancel run:**
  - `POST /runs/{id}/cancel` → `202` (`{"run_id", "status": "cancelling"}`); `404` unknown run; `409` if the run has already ended. Asking again while the cancel is pending is accepted.
  - Sets a new `runs.cancel_requested_at` column (migration `0011_run_cancel`). A run waiting at a gate is queued again and the API enqueues it.
  - A **running** run: the worker checks the flag every `cancel_poll_s` (1 s) next to its lease heartbeat and cancels the attempt with `task.cancel("cancelled by user")`, *without* detaching the sink, so `node_cancelled` and `run_cancelled` (reason `cancelled by user`) are written. The engine takes the reason from the cancel message.
  - A **queued or waiting** run: the worker that claims it sees the flag and writes `run_cancelled` without running any node (`run_started` first if it never started). A sandbox the run kept at a gate is discarded (`SandboxManager.discard`).
  - The summary projection already maps `run_cancelled` → `cancelled`.

### Out of scope
- Sticky approval dock, waiting badge in the sidebar and tab title: 2.6.
- Rerun action: 2.6.
- Cost in USD per node and run: 3.1.
- Graph tab: 3.5.
- Editable artifacts / diffs at a gate: 3.6.
- A one-line intent per tool call written by the agent (needs a `description` argument on the platform tools): logged in `TODO.md`, not part of 2.5.
- Virtualised timeline for very long runs (revisit with 10.4 performance targets).
- Resume a cancelled run from its checkpoint (rerun is 2.6; resume is a later option).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where merging happens | A pure reducer over the event list (`buildTimeline(events)`), memoised on the events | Easy to unit-test against a recorded run; replay after reconnect gives the same result by construction. |
| Turn boundary | A `tool_call` closes the current message; `message` replaces the last turn's merged text | Matches the Claude adapter: each API call streams text, then tool calls; the final call's text is the `message`. |
| Server buffer | Engine-side per node/item, 250 ms, first chunk written at once, flushed before any non-delta event | Tech-stack decision. The log shrinks by ~10–50× on a docs run with no change to the event schema or the client. |
| Header liveness | The run's own event stream, not the workspace summaries stream | One connection instead of two; the events already carry status, PR and timings. |
| Tool call display (user feedback) | One line per call, quiet calls grouped into a summary line, previews only for writes, commits, PRs and failures | Like Claude Code and Copilot: a docs module makes 16+ calls, and a card per call buried the agent's output. |
| Timeline rail (user choice) | Status icon markers on a vertical line, badges only where attention is needed | Reads top to bottom like Claude Code's transcript; status stays icon + label, never colour alone. |
| Raw HTML in messages | Dropped (`skipHtml`), not shown as text | Agents write `<!-- -->` markers into docs; dropping them reads cleanly and still never renders HTML. |
| Follow-scroll on open | Start not following; ignore the first 1.5 s of a live stream | The replay of stored events made the page jump to the bottom on open. |
| Cancel signal (user choice to include) | `runs.cancel_requested_at`, polled by the worker every second | The DB row is already the source of run state; survives worker restarts; no new channel. |
| Cancel of a waiting/queued run | Re-enqueue; the claiming worker writes `run_cancelled` | Only workers write events, so `seq` stays gap-free and single-writer. |
| Cancel reason | `task.cancel("cancelled by user")`; the engine logs the message as the reason | One code path for every cancel; LangGraph passes the message through (checked with a map). |
| Usage footer (user choice) | Tokens per step only | USD and per-run totals belong to 3.1's normalised cost. |
| JSON viewer | Small in-house component (`json-view.tsx`) on `<details>` | Tech stack asks for "collapsible JSON viewer" without naming one; accessible by default, no dependency. |
| Chunks in Raw events (user requirement) | Fold consecutive deltas of one node/item into one row, expandable | A message is read as one paragraph everywhere; the per-chunk detail stays one click away for audit. |
| Test data | A docs-like run recorded from the engine on the fake runtime (`scripts/record_console_fixture.py`) | The reducer is tested on the real event shapes, and the fixture can be recorded again when they change. |

## Open questions
- None.
