# Plan: Minimal monitor page: list events of a run

## 1. API: CORS and a typed event schema
- [ ] `packages/api/src/agentic_api/settings.py`: add `cors_origins: list[str] = ["http://localhost:3000"]` (env `CORS_ORIGINS`, JSON list).
- [ ] `packages/api/src/agentic_api/app.py`: add `CORSMiddleware` with `allow_origins=settings.cors_origins`, methods `GET, POST`, headers `content-type` and `last-event-id`.
- [ ] `packages/api/src/agentic_api/runs/routes.py`: document the 200 response of `stream_run_events` as `text/event-stream` with `RunEvent` as its item schema, so the component lands in OpenAPI.
- [ ] `docker-compose.yml` / `.env.example`: pass `CORS_ORIGINS` to `api` (default `["http://localhost:3000"]`).
- [ ] Regenerate: `uv run python scripts/export_openapi.py && (cd web && pnpm gen:api)`. Commit `web/openapi.json` and `web/src/api/schema.d.ts`.

## 2. Web: event stream hook
- [ ] `web/src/api/client.ts`: export `apiBaseUrl()` (same `NEXT_PUBLIC_API_URL` fallback) so the hook and the client share it.
- [ ] `web/src/runs/types.ts`: `type RunEvent = components["schemas"]["RunEvent"]`, `TERMINAL_TYPES`, `RunStatus`.
- [ ] `web/src/runs/use-run-events.ts`: `useRunEvents(runId)` opens `EventSource` and listens to the named events (SSE frames carry `event: <type>`, so it uses one shared handler for the known types plus `message`). It parses `data`, inserts by `seq` without duplicates, records `receivedAt = Date.now()` per event, sets the status from terminal events and then calls `close()`. On `error` before any event, it probes the events URL with `fetch`: 404 → `not_found`, otherwise `error`. It cleans up on unmount.
- [ ] `web/src/runs/summarize.ts`: `summarizePayload(event)` → one-line string (text for `text_delta`, token counts for `usage`, error message for `run_failed`, otherwise truncated JSON).
- [ ] Vitest: `use-run-events.test.ts` with a fake `EventSource` class on `globalThis`, and `summarize.test.ts`.

## 3. Web: run page and start form
- [ ] `web/src/app/runs/[id]/page.tsx`: server shell (awaits `params`) that renders `<RunEvents runId={id} />`.
- [ ] `web/src/runs/run-events.tsx` (client): status badge plus a table with `data-testid="event-row"` and `data-seq`, `data-received-at`, `data-created-at` on each row. Empty, `not_found` and `error` states. Payload as text only.
- [ ] `web/src/runs/sample-spec.ts`: a one-node `WorkflowSpec` (the same shape as `single-agent.json`).
- [ ] `web/src/runs/start-run-form.tsx` (client): input field + button, `client.POST("/runs", …)`, then `router.push(`/runs/${run_id}`)`. Shows 422/network errors inline and disables the button while it posts.
- [ ] `web/src/app/page.tsx`: keep `app-root` and the heading, and add `<StartRunForm />`.
- [ ] Vitest: `run-events.test.tsx` (rows in seq order, status badge, not-found state, HTML in a payload shown as text) and `start-run-form.test.tsx` (posts the sample spec, navigates, shows an error).

## 4. End to end, docs, wrap-up
- [ ] `web/e2e/monitor.spec.ts`: from `/`, start a run through the form, land on `/runs/<id>`, wait for `run_completed`, and assert `receivedAt - createdAt < 1000` for every row. No console errors. Second test: `POST /runs` through Playwright `request`, then open the page directly.
- [ ] Check that the existing compose e2e CI job runs the new spec unchanged (worker `FAKE_STEP_DELAY_S=0.5`, fake runtime).
- [ ] README: a "Monitor" section after "Runs API" (open `http://localhost:3000` and start a run, or open `/runs/<id>` after a curl POST). Document `CORS_ORIGINS`.
- [ ] `CHANGELOG.md` entry. The roadmap row is marked done through the `complete-phase` skill on the implementation PR.
