# Minimal monitor page: list events of a run

Roadmap phase: 0.8
Branch: plan/0.8-minimal-monitor-page

## Context
Phases 0.5 to 0.7 store every run step in `run_events` and stream them from `GET /runs/{id}/events` (SSE), on the fake runtime or on Claude. The only way to see a run today is `curl -N`. This phase adds the first browser view of a run. It closes Milestone 0, the walking skeleton: a browser starts a run, the API queues it, the worker runs it, and the events come back to the browser live.

It depends on 0.1 (Next.js app, generated API client) and 0.6 (`POST /runs`, the SSE stream), both done. It unblocks 2.5 (monitor v1 with a graph and node detail) and 2.6 (approval cards), which grow this page.

Drivers:
- Principle **Transparency**: every agent action is visible live. The mission's success metric is "monitor events shown within 1 s", and that is this phase's "Done when".
- Principle **Small, verifiable steps**: a flat list of events. No graph and no cost view yet.
- Principle **Repo content is data**: event payloads (agent text, tool output) are rendered as text and never as HTML.
- Tech stack: Next.js App Router + TypeScript strict, `EventSource` for SSE, the API client generated from FastAPI's OpenAPI spec, Tailwind.

## Scope
### In scope
- **CORS on the API.** A new `cors_origins` setting (env `CORS_ORIGINS`, default `["http://localhost:3000"]`) feeds Starlette's `CORSMiddleware` (GET/POST, `content-type`, `last-event-id`). The browser calls the API directly at `NEXT_PUBLIC_API_URL`.
- **`RunEvent` in the OpenAPI spec.** The SSE route documents its `text/event-stream` response with `RunEvent` as the item schema, so `pnpm gen:api` emits a `RunEvent` type for the web. The generated `web/openapi.json` and `schema.d.ts` are regenerated and committed, and the existing CI drift check covers them.
- **Start form on the home page** (`/`). A client component with an input text field and a "Start sample run" button. It POSTs a fixed sample spec (one `agent` node, in `web/src/runs/sample-spec.ts`, typed as the generated `WorkflowSpec`) through the generated client, then navigates to `/runs/<run_id>`. A 422 or network error is shown inline.
- **Run page** `/runs/[id]`. A server route shell with a client component that:
  - opens `EventSource` on `${API_URL}/runs/{id}/events`;
  - adds a row per event, ordered by `seq` and de-duplicated by `seq` (a reconnect resends nothing, because the browser sends `Last-Event-ID`, but the list stays idempotent anyway);
  - shows for each row: `seq`, `type`, `node_id`, `created_at` (local time) and a one-line payload summary (`text_delta` → the text, `usage` → token counts, otherwise compact JSON), all rendered as text;
  - shows the status: `connecting` → `live` → `completed` / `failed` / `cancelled` from the terminal event. It closes the `EventSource` after a terminal event so the browser does not reconnect;
  - shows an error state for an unknown run (404) or for a stream that keeps failing.
- **`useRunEvents(runId)` hook** (`web/src/runs/use-run-events.ts`): plain `EventSource`, typed with the generated `RunEvent`, returning `{ events, status, error }`.
- A README "Monitor" section: start a run from the browser or with curl, then watch it.

### Out of scope
- `GET /runs` / a runs list page, and a `GET /runs/{id}` summary: added when a later monitor phase needs them.
- Graph view, node detail, transcripts, tool-call detail (2.5). Cost / USD per node (2.1).
- TanStack Query: no REST data to cache yet. It comes in with 2.5.
- Editing the spec in the browser, or choosing a provider. The sample spec is fixed, and the worker's `AGENTIC_RUNTIME` picks fake or Claude.
- Cancel button (no cancel endpoint yet). Auth, workspaces (1.4).
- Collapsing consecutive `text_delta` rows into one message: each event is one row in this phase.
- A same-origin proxy (Next.js rewrites). We use CORS instead.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Browser → API | Direct calls with CORS, origins from `CORS_ORIGINS` | No proxy that might buffer SSE. `events_url` from `POST /runs` is already absolute. One middleware and one setting. |
| Starting a run | Home-page form with a fixed sample spec + free-text input | The demo needs no terminal. Spec editing belongs to the canvas (4.x). |
| SSE client | Native `EventSource` in a small hook, no library | Tech-stack choice. Built-in reconnect with `Last-Event-ID` matches the API's resume by `seq`. |
| Event types on the web | Generated `RunEvent` from OpenAPI | Tech stack: contracts are shared through the generated client, not hand-written types. |
| Data layer | No TanStack Query yet | Nothing to cache. Add it with 2.5, when REST reads appear. |
| Rendering payloads | Text only, a one-line summary per event | Principle 5: agent and repo content is data. No `dangerouslySetInnerHTML`. |
| Proving "within 1 s" | Each row records its receive time, and e2e compares it with the event's `created_at` | Measures the real latency from DB write to browser, not just "something showed up". |

## Open questions
- None.
