# Plan: Run console v2

Order: pure reducer first (user choice), then components, then the page and tabs, then the backend (buffer, cancel). After each group the app still builds and the existing pages work.

## 1. Timeline model (pure reducer)
- [ ] Record a fixture of a docs-like run on the fake runtime (sequence + map over 3 modules + reviewer loop + gate + tool calls) as `web/src/runs/fixtures/docs-run.json`, plus small hand-written fixtures per edge case.
- [ ] Add `web/src/runs/timeline.ts`: types `Timeline`, `Step`, `MapItem`, `Iteration`, `Turn` (`message` | `tool`), and `buildTimeline(events: RunEvent[]): Timeline`.
  - Steps in order of first appearance; status/duration from `node_*`, `gate_*`, `loop_*`, `map_item_*` events.
  - Turns: deltas append to the open message turn; `tool_call` closes it and opens a tool turn keyed by `call_id`; `tool_result` completes it; `message` replaces the last message turn's text and marks it final.
  - `usage` summed per step; errors attached to the step.
- [ ] Vitest `timeline.test.ts`: fixture gives one message per agent turn; message replaces deltas; tool pairing (incl. missing result, error result); map items nested with their own turns; loop iterations; unknown event types ignored; idempotent under duplicate `seq`.

## 2. Display components
- [ ] Add `react-markdown` and `remark-gfm` to `web/package.json`.
- [ ] `web/src/runs/console/agent-message.tsx`: Markdown, no raw HTML, safe links, streaming caret.
- [ ] `web/src/components/json-view.tsx`: pretty JSON, collapsed past depth 2, Copy button, scrolls in its own box; falls back to mono text for non-JSON.
- [ ] `web/src/runs/console/tool-card.tsx`: collapsible card (Radix Collapsible or `<details>`), name, status icon, duration, arguments + result via `JsonView`.
- [ ] `web/src/runs/console/step.tsx`: step header (status icon, node id/label, duration), turns, nested map items and iterations, usage footer, inline error, `GatePanel` when waiting.
- [ ] Component tests: HTML in a message is rendered as text; tool card expands and copies; nested map items; usage footer.

## 3. Console page: header, tabs, live behaviour
- [ ] `web/src/runs/use-run-summary.ts`: `useQuery(["runs", id])` over `GET /runs/{id}`, patched by `useRunsStream`.
- [ ] `web/src/runs/console/run-header.tsx`: `PageHeader` with status, workflow, repo/branch, started, live duration, PR link; actions Copy run id and Cancel (disabled until group 5 lands; then wired with a confirm dialog and toast).
- [ ] `web/src/runs/console/run-console.tsx`: tabs Timeline / Raw events (`?tab=`), skeleton / not-found / error states.
- [ ] Add `foldDeltas(events)` in `web/src/runs/timeline.ts`: consecutive `text_delta`s with the same `node_id` and `item` become one row (joined text, first/last `seq`, count, the chunks). Vitest: fold breaks on another event type, node or item; joined text equals the concatenation.
- [ ] Move today's table into `web/src/runs/console/raw-events.tsx`, render folded rows (expandable to the chunks), and add type and node filters.
- [ ] `web/src/runs/use-follow-scroll.ts` + "Jump to latest" pill; `aria-live` status announcer.
- [ ] Replace `RunEvents` in `web/src/app/runs/[id]/page.tsx`; remove `run-events.tsx` once nothing uses it; update the `monitor` e2e selectors that relied on rows.

## 4. Server delta buffer (engine)
- [ ] `packages/engine/src/agentic_engine/graph/deltas.py`: `DeltaBuffer(emit, interval=0.25)` with `add(event)`, a timer flush, and `flush()`; non-delta events flush first, then pass through.
- [ ] Use it in `_run_step` (`compile.py`) per node/item; flush in `finally` (incl. `CancelledError`) before `node_*` end events.
- [ ] pytest: many deltas within 250 ms → one event with the joined text; a slow stream still writes within ~250 ms; a tool call / message / node end flushes first; concatenated text equal to input; map items buffer separately; cancellation flushes.

## 5. Cancel run
- [ ] Alembic migration: `runs.cancel_requested_at timestamptz null`; model field in `agentic_store/models.py`.
- [ ] `agentic_store/runs.py`: `request_cancel(run_id)` (raises not-found / already-ended) and `cancel_requested(run_id)`.
- [ ] `POST /runs/{id}/cancel` (`operation_id="cancelRun"`, 202/404/409) in `runs/routes.py`; enqueue the run if it is queued or waiting; NOTIFY.
- [ ] Worker: the lease loop checks `cancel_requested_at` (renewal returns it; check interval ≤ 2 s) and cancels the attempt with the sink still attached, so `node_cancelled` / `run_cancelled {"reason": "cancelled by user"}` are written. On claim, a flagged run writes `run_cancelled` straight away. Sandbox cleanup as for any ended run.
- [ ] pytest (Testcontainers): cancel running → `run_cancelled` and status `cancelled`; cancel waiting at a gate → `cancelled`, gate can no longer be approved (409); cancel ended → 409; unknown → 404; double cancel → 202.
- [ ] Regenerate `web/openapi.json` and `web/src/api/schema.d.ts`; wire the header Cancel button.

## 6. Cleanup
- [ ] Mark roadmap 2.5 done in the implementation PR (`complete-phase` skill).
