# Plan: Run console v2

Order: pure reducer first (user choice), then components, then the page and tabs, then the backend (buffer, cancel). After each group the app still builds and the existing pages work. Groups 7 and 8 were added after reviewing the console on a real docs run.

## 1. Timeline model (pure reducer)
- [x] Record a docs-like run on the fake runtime (tool node, map over 3 modules with two streamed turns around a tool call, reduce, review loop, gate) as `web/src/runs/fixtures/docs-run.json`, with `scripts/record_console_fixture.py`; hand-written events per edge case in the tests.
- [x] Add `web/src/runs/timeline.ts`: types `Timeline`, `Step`, `MapItem`, `Iteration`, `Turn` (`message` | `tool`), and `buildTimeline(events)`.
  - Steps in order of first appearance; status/duration from `node_*`, `gate_*`, `loop_*`, `map_item_*` events.
  - Turns: deltas append to the open message turn; `tool_call` closes it and opens a tool turn keyed by `call_id`; `tool_result` completes it; `message` replaces the last message turn's text and marks it final.
  - `usage` summed per step; errors attached to the step.
- [x] Vitest `timeline.test.ts`: one message per agent turn; message replaces deltas; tool pairing (missing result, error result); map items nested; loop iterations; unknown event types ignored; duplicate `seq` ignored.

## 2. Display components
- [x] Add `react-markdown` and `remark-gfm` to `web/package.json`.
- [x] `web/src/runs/console/agent-message.tsx`: Markdown, no raw HTML, no images, safe links, streaming caret.
- [x] `web/src/components/json-view.tsx`: pretty JSON, collapsed past depth 2, Copy button, scrolls in its own box; mono text for non-JSON.
- [x] Tool call display (first a card per call, replaced in group 7).
- [x] `web/src/runs/console/step-view.tsx`: step title, turns, nested map items and iterations, usage footer, inline error, `GatePanel` when waiting.
- [x] shadcn-style `tabs`, `collapsible` and `alert-dialog` primitives in `web/src/components/ui`.
- [x] Component tests (`step-view.test.tsx`).

## 3. Console page: header, tabs, live behaviour
- [x] `web/src/runs/use-run-detail.ts`: `useQuery(["run", id])` over `GET /runs/{id}`, refetched when the event stream moves on (status, gate, PR).
- [x] `web/src/runs/console/run-header.tsx`: `PageHeader` with status, workflow, repo/branch, started, live duration, PR link; Copy run id and Cancel.
- [x] `web/src/runs/console/run-console.tsx`: tabs Timeline / Raw events (`?tab=`), not-found / lost-stream / failure states.
- [x] `foldDeltas(events)` in `timeline.ts`, with tests.
- [x] `web/src/runs/console/raw-events.tsx`: folded rows (expandable to the chunks), type and node filters.
- [x] `web/src/runs/use-follow-scroll.ts` + "Jump to latest" pill; `aria-live` status.
- [x] `web/src/app/runs/[id]/page.tsx` renders `RunConsole`; `run-events.tsx` removed (its tests ported to `run-console.test.tsx`); `e2e/monitor.spec.ts` reads the folded raw rows.

## 4. Server delta buffer (engine)
- [x] `packages/engine/src/agentic_engine/graph/deltas.py`: `DeltaBuffer(write, interval=0.25)` with `emit`, a timer flush, `flush()` and `close()`.
- [x] Used in `_run_step` (`compile.py`) per node/item; closed in a `finally` before `node_*` end events (incl. `CancelledError`).
- [x] pytest `test_deltas.py`: burst merged after the first chunk; slow stream chunk by chunk; timer flush; other events flush first; close; per map item in a real run; flush on cancel.

## 5. Cancel run
- [x] Migration `0011_run_cancel`: `runs.cancel_requested_at`; model field; `test_migrations.py` head updated.
- [x] `agentic_store/cancel.py`: `request_cancel` (returns the status before; `RunNotFoundError` / `RunEndedError`), `cancel_requested`, `run_ended`.
- [x] `POST /runs/{id}/cancel` (`operation_id="cancelRun"`, 202/404/409); enqueue a run that was waiting.
- [x] Engine: `run_cancelled` takes its reason from the cancel message.
- [x] Worker: `_watch_cancel` every `cancel_poll_s` next to the heartbeat; `attempt.cancel(USER_CANCEL_REASON)` with the sink attached; `_end_cancelled` for a run claimed with the flag; `SandboxManager.discard` (Docker, fake, test doubles) for a sandbox kept at a gate.
- [x] pytest: API (running, waiting at a gate then approve → 409, queued before any worker, unknown → 404, ended → 409, asked twice → 202), worker (kept sandbox removed), engine (cancel reason).
- [x] Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`; `cancel-run-button.tsx` with confirm dialog and toasts.

## 6. Cleanup
- [x] Roadmap 2.5 marked done for PR #27 (by CI on the PR branch).
- [x] `tech-stack.md`: cancel endpoint in the API contract; run console rules updated for the rail, tool lines and live line.

## 7. Tool calls as compact lines (after a review on a real docs run)
- [x] `web/src/runs/console/tool-describe.ts`: `describeTool` (icon, done/doing verb, target per `repo.*` / `github.*` tool), `summarizeTools`, `toolPreview`.
- [x] `web/src/runs/console/tool-calls.tsx`: `ToolCallRow` (one line, opens to arguments and result, inline preview) and `ToolCallGroup` (summary line, live "Reading …"); the per-call card removed.
- [x] Map items named by `path` + `kind` (`item-name.ts`); a one-step item is not headed twice.
- [x] Raw HTML in messages dropped (`skipHtml`).
- [x] Accessible names keep spaces between their parts ("Read src/app.ts 2s").
- [x] Tests for describing, summarising, rows, groups and previews.

## 8. Rail, live line, previews (inspired by Claude Code)
- [x] `web/src/runs/console/rail.tsx`: `Rail`, `RailItem` (line across `--rail-gap`), `StatusMarker` (icon + screen-reader label), `DotMarker`, `IconMarker`; the step view built on it.
- [x] `web/src/runs/console/activity.ts` + `activity-line.tsx`: the latest running step's action, shown at the end of a live timeline.
- [x] Previews for writes, commits, PRs and failures; such calls stand on their own line.
- [x] Follow-scroll opens at the top and ignores the replay of stored events.
- [x] Tests for previews, the rail markers and `currentActivity`.
- [x] Next idea logged in `TODO.md`: a one-line intent per tool call.
