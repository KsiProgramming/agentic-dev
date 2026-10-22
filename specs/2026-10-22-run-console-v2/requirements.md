# Run console v2

Roadmap phase: 2.5
Branch: plan/2.5-run-console-v2

## Context
`/runs/{id}` is still the 0.8 debug view: one table row per event, so a docs run shows hundreds of `text_delta` rows and the tool calls are raw payloads. The Runs page (2.4) now links every run here, so this is the page users land on. This phase turns it into the run console described in [tech-stack.md → Run console](../tech-stack.md#run-console): a header, a timeline that reads as a story, and the raw log one tab away.

Depends on 2.1 (tokens, `StatusBadge`, states), 2.2 (shell, `PageHeader`), 2.3 (`GET /runs/{id}` summary) and 2.4 (TanStack Query, `useRunsStream`). All are done. It does not depend on 1.12, which is still unplanned. It unblocks 2.6 (approval dock sits on this page), 2.7 (Rerun action in this header), 3.1 (cost per node in the usage footer) and 3.5 (Graph tab opens the node detail from here).

Principles and choices that apply:
- **Mission 8, Enterprise-grade, calm UI:** runs read as a story (nodes, messages, tool calls); the raw event log is one click away, not the default.
- **Mission 6, Transparency:** every agent action and tool call stays visible; nothing is hidden, only grouped.
- **Mission 5, content is data:** agent messages render as Markdown with raw HTML disabled; tool output is shown as text/JSON, never interpreted.
- **Mission 3, humans approve irreversible actions:** Cancel only stops the run; it never pushes or opens anything.
- **Tech stack → Event display:** merge deltas on the client *and* buffer writes on the server (250 ms). The append-only log and SSE replay stay unchanged.
- **Tech stack → Frontend:** `react-markdown` for messages, a collapsible JSON viewer, TanStack Query, `lucide-react`, JetBrains Mono for JSON and ids.

## Scope
### In scope
- **Timeline model (pure, client):** a reducer from the ordered `RunEvent[]` to a timeline:
  - One step per node in run order (first `node_started` / `gate_waiting`), with status and duration from its lifecycle events. Loop iterations are shown as separate entries of the step ("Iteration 2").
  - Map items nested under their map node (`map_item_started` / `map_item_completed`, and the `item` tag on child events), each with its own status.
  - Inside a step, a list of **turns**. Consecutive `text_delta` events form one growing message; a `tool_call` closes the current message. The `message` event replaces the merged text of the last turn (or adds one if none is open).
  - `tool_call` and its `tool_result` (same `call_id`) form one tool card; a result that has not arrived yet shows the card as running.
  - `usage` events summed per step into a footer (input/output tokens; USD is 3.1).
  - Node errors (`node_failed` payload, agent `failed`) shown inline in the step.
- **Header** (`PageHeader`): status badge (live), workflow name, repo (`owner/name`, mono) and branch, started time, live duration, PR link once `pr_opened` arrives. Actions: **Cancel** (only while queued, running or waiting; confirm dialog) and **Copy run id**. Data from `GET /runs/{id}`, kept live by `useRunsStream`.
- **Message rendering:** `react-markdown` with HTML disabled (no `rehype-raw`), links open in a new tab with `rel="noreferrer"`; a blinking caret while the turn is still streaming.
- **Tool cards:** collapsible (collapsed by default), header with tool name, status icon and duration; body with arguments and result. JSON pretty-printed, collapsed after 2 levels, a Copy button; non-JSON output as mono text. Wide content scrolls inside its own box. `is_error` results use the failed status style.
- **One message, one row (both views):** chunks of the same message are never shown one per row. On the Timeline they form one message block that reads as complete paragraphs (text joined with no separator, so words and line breaks are restored as the model wrote them). On Raw events, consecutive `text_delta` events of the same node and map item are folded into **one row** showing the joined text, the `seq` range and the chunk count ("`text_delta` × 37, seq 40–76"); the row can be expanded to list the individual chunks for debugging. A different event or a different node/item ends the fold.
- **Tabs:** Timeline (default) and Raw events. Raw events is today's event table, with deltas folded as above, plus filters by type and by node. The tab is kept in the URL (`?tab=raw`).
- **Live behaviour:** auto-scroll follows new content only while the user is at the bottom; otherwise a "Jump to latest" pill appears. `aria-live="polite"` announces run status changes.
- **Gate panel:** the existing inline `GatePanel` stays, rendered in the waiting gate's step. The sticky dock is 2.6.
- **Server delta buffer (engine):** a per-node buffer around `on_event` in `_run_step`. `text_delta`s are merged and written at most once every 250 ms; the buffer is flushed before any other event of that node (tool call, message, usage, node end) and on cancellation, so order and the concatenated text are unchanged. Each map item has its own buffer.
- **Cancel run:**
  - `POST /runs/{id}/cancel` → `202`; `404` unknown run; `409` if the run has already ended. Idempotent while the cancel is pending.
  - Sets a new `runs.cancel_requested_at` column (Alembic migration) and wakes the run's worker.
  - A **running** run: the worker sees the flag on its next lease renewal (heartbeat shortened to ≤ 2 s check, or a `LISTEN` wake-up) and cancels the attempt *without* detaching the sink, so `node_cancelled` and `run_cancelled` (reason `"cancelled by user"`) are written. The sandbox is removed as for any ended run.
  - A **queued or waiting** run: the API enqueues it; the worker that claims it sees the flag and writes `run_cancelled` without running any node.
  - The summary projection already maps `run_cancelled` → `cancelled`.

### Out of scope
- Sticky approval dock, waiting badge in the sidebar and tab title: 2.6.
- Rerun action: 2.7.
- Cost in USD per node and run: 3.1.
- Graph tab: 3.5.
- Editable artifacts / diffs at a gate: 3.6.
- Virtualised timeline for very long runs (revisit with 10.4 performance targets).
- Resume a cancelled run from its checkpoint (rerun is 2.7; resume is a later option).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where merging happens | A pure reducer over the event list (`buildTimeline(events)`), memoised on the event count | Easy to unit-test against a recorded run; replay after reconnect gives the same result by construction. |
| Turn boundary | A `tool_call` closes the current message; `message` replaces the last turn's merged text | Matches the Claude adapter: each API call streams text, then tool calls; the final call's text is the `message`. |
| Server buffer | Engine-side per node/item, 250 ms, flushed before any non-delta event | Tech-stack decision. The log shrinks by ~10–50× on a docs run with no change to the event schema or the client. |
| Cancel signal (user choice to include) | `runs.cancel_requested_at` checked by the worker, not a Redis message | The DB row is already the source of run state and the lease loop already polls it; survives worker restarts. |
| Cancel of a waiting/queued run | Re-enqueue; the claiming worker writes `run_cancelled` | Only workers write events, so `seq` stays gap-free and single-writer. |
| Usage footer (user choice) | Tokens per step only | USD and per-run totals belong to 3.1's normalised cost. |
| JSON viewer | Small in-house component (`json-view.tsx`) on `<details>` | Tech stack asks for "collapsible JSON viewer" without naming one; ~100 lines, accessible by default, no dependency. |
| Markdown | `react-markdown` + `remark-gfm`, no `rehype-raw` | Tech-stack choice; HTML disabled keeps payloads as data. |
| Chunks in Raw events (user requirement) | Fold consecutive deltas of one node/item into one row, expandable | A message is read as one paragraph everywhere; the per-chunk detail stays one click away for audit. |
| Raw events | Kept as a tab, filters by type and node | Tech stack: kept for debugging and audit. |

## Open questions
- None.
