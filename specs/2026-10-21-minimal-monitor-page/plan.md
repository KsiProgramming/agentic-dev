# Plan: Minimal monitor page: list events of a run

## 1. API: CORS and a typed event schema
- [x] `packages/api/src/agentic_api/settings.py`: add `cors_origins: list[str] = ["http://localhost:3000"]` (env `CORS_ORIGINS`, JSON list).
- [x] `packages/api/src/agentic_api/app.py`: add `CORSMiddleware` with `allow_origins=settings.cors_origins`, methods `GET, POST`, headers `content-type` and `last-event-id`.
- [x] `packages/api/src/agentic_api/runs/routes.py`: document the 200 response of `stream_run_events` as `text/event-stream` with `RunEvent` as its item schema (through `openapi_extra`: FastAPI skips this for routes that yield `ServerSentEvent`). `app.py` adds `RunEvent` to the OpenAPI components, so `components["schemas"]["RunEvent"]` exists for the web.
- [x] `docker-compose.yml` / `.env.example`: pass `CORS_ORIGINS` to `api` (default `["http://localhost:3000"]`).
- [x] Regenerate: `uv run python scripts/export_openapi.py && (cd web && pnpm gen:api)`. Commit `web/openapi.json` and `web/src/api/schema.d.ts`.

## 2. Web: event stream hook
- [x] `web/src/api/client.ts`: export `apiBaseUrl()` (same `NEXT_PUBLIC_API_URL` fallback) so the hook and the client share it.
- [x] `web/src/runs/types.ts`: `type RunEvent = components["schemas"]["RunEvent"]`, `RUN_END_STATUS` / `runOutcome`, `StreamStatus` and `EVENT_TYPES` (every `event:` name the stream sends).
- [x] `web/src/runs/use-run-events.ts`: `useRunEvents(runId)` opens `EventSource` and listens to the named events (SSE frames carry `event: <type>`, so it uses one shared handler for every name in `EVENT_TYPES`, `message` included). It parses `data`, inserts by `seq` without duplicates (`insertEvent`), records `receivedAt = Date.now()` per event, sets the status from terminal events and then calls `close()`. On `error` before any event, it probes the events URL with `fetch`, because `EventSource` hides the status and does not retry a 404: 404 → `not_found`, a closed stream → `error`, otherwise the browser keeps retrying. It cleans up on unmount.
- [x] `web/src/runs/summarize.ts`: `summarizePayload(event)` → one-line string (text for `text_delta` / `message`, token counts for `usage`, error for the failed types, tool name + arguments, tool output, otherwise truncated JSON).
- [x] Vitest: `use-run-events.test.ts` and `summarize.test.ts`, with a scriptable `FakeEventSource` and a `runEvent` builder in `web/src/runs/testing.ts`. `web/vitest.setup.ts` unmounts after each test (Vitest globals are off).

## 3. Web: run page and start form
- [x] `web/src/app/runs/[id]/page.tsx`: server shell that awaits `params` inside `<Suspense>` (required by `cacheComponents` for an unknown dynamic param) and renders `<RunEvents key={id} runId={id} />`.
- [x] `web/src/runs/run-events.tsx` (client): status badge plus a table with `data-testid="event-row"` and `data-seq`, `data-received-at`, `data-created-at` on each row. Empty, `not_found` and `error` states. Payload as text only.
- [x] `web/src/runs/sample-spec.ts`: a one-node `WorkflowSpec` (the same shape as `single-agent.json`).
- [x] `web/src/runs/start-run-form.tsx` (client): input field + button, `client.POST("/runs", …)`, then `router.push(`/runs/${run_id}`)`. Shows 422/network errors inline and disables the button while it posts.
- [x] `web/src/app/page.tsx`: keep `app-root` and the heading, and add `<StartRunForm />`.
- [x] Vitest: `run-events.test.tsx` (rows in seq order, status badge, not-found state, HTML in a payload shown as text) and `start-run-form.test.tsx` (posts the sample spec, navigates, shows an error).

## 4. End to end, docs, wrap-up
- [x] `web/e2e/monitor.spec.ts`: from `/`, start a run through the form, land on `/runs/<id>`, wait for `run_completed`, and assert `receivedAt - createdAt < 1000` for every live row (written after the stream connected; at least 3). No console errors. Second test: `POST /runs` through Playwright `request` (`E2E_API_URL`, default `http://localhost:8000`), then open the page directly. Third: an unknown run id shows "Run not found."
- [x] Check that the existing compose e2e CI job runs the new spec unchanged (worker `FAKE_STEP_DELAY_S=0.5`, fake runtime).
- [x] README: a "Monitor" section after "Runs API" (open `http://localhost:3000` and start a run, or open `/runs/<id>` after a curl POST). Document `CORS_ORIGINS`.
- [x] `CHANGELOG.md` entry. The roadmap row is marked done through the `complete-phase` skill on the implementation PR.
